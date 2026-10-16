"""Behaviour kept by the performance changes: concurrent reads, the pruned filename
walk, the wikilink fast path and the per-note body-line cache. Not timing tests.

Every identifier is synthetic and generated from a seeded RNG.
"""

from __future__ import annotations

import errno
import os
import random
import threading
import time
import tracemalloc
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from helpers import TODAY, body_for, make_vault, note_text, write

from labbrain import index, lint, notes, phi, readpool, vault
from labbrain.layout import iter_note_files
from labbrain.lint.rules import link_rules
from labbrain.notes import (
    future_agents_block,
    h2_headings,
    iter_body_lines,
    parse_note,
    parse_note_text,
    wikilink_targets,
)
from labbrain.phi import ScanSettings, scan
from labbrain.vault import Vault

RNG = random.Random(20261015)


def phone() -> str:
    return f"{RNG.randrange(200, 999)}-555-{RNG.randrange(1000, 9999)}"


def _jittered(fn: Callable[[Path], Any]) -> Callable[[Path], Any]:
    """`fn` with a random delay, so worker reads finish out of submission order."""
    jitter = random.Random(7)
    delays: dict[Path, float] = {}

    def wrapper(path: Path) -> Any:
        delay = delays.setdefault(path, jitter.uniform(0, 0.004))
        time.sleep(delay)
        return fn(path)

    return wrapper


def _many_notes(root: Path) -> Path:
    make_vault(root)
    for i in range(12):
        write(
            root,
            f"experiments/EXP-2026100{i % 9 + 1}-e{i}.md",
            note_text(f"EXP-x{i}", "experiment"),
        )
        write(root, f"concepts/sub{i % 3}/c{i}.md", note_text(f"c{i}", "concept", sources=["x"]))
    # Duplicate IDs in different folders: group order must follow the sorted walk.
    write(root, "concepts/dup.md", note_text("dup", "concept", sources=["x"]))
    write(root, "decisions/dup.md", note_text("dup", "decision"))
    write(root, "ideas/inbox/dup.md", "no frontmatter [[c1]]\n")
    return root


# 1. Vault.load reads concurrently but keeps every ordering.


def test_load_order_matches_a_sequential_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _many_notes(tmp_path).resolve()
    monkeypatch.setattr(readpool, "read_workers", lambda: 2)  # window 4 < 27 notes
    monkeypatch.setattr(vault, "read_note_text", _jittered(notes.read_note_text))
    loaded = Vault.load(root)
    sequential = [parse_note(path, root) for path in iter_note_files(root)]
    assert list(loaded.by_rel) == [n.rel for n in sequential]
    assert list(loaded.by_rel.values()) == sequential
    first_seen: dict[str, str] = {}
    for note in sequential:
        first_seen.setdefault(note.stem, note.rel)
    assert list(loaded.notes) == list(first_seen)
    assert [n.rel for n in loaded.notes.values()] == list(first_seen.values())
    assert {k: [n.rel for n in g] for k, g in loaded.duplicates.items()} == {
        "dup": ["ideas/inbox/dup.md", "concepts/dup.md", "decisions/dup.md"]  # NOTE_FOLDERS order
    }


def test_read_error_in_a_worker_becomes_a_schema_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_vault(tmp_path).resolve()
    write(root, "concepts/fine.md", note_text("fine", "concept", sources=["x"]))
    bad = write(root, "concepts/bad.md", note_text("bad", "concept", sources=["x"]))
    real_read_bytes = Path.read_bytes

    def read_bytes(self: Path, *args: Any, **kwargs: Any) -> bytes:
        if self == bad:
            raise PermissionError("denied")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    loaded = Vault.load(root)
    assert loaded.notes["bad"].errors == ["cannot read file"]
    assert loaded.notes["bad"].text == "" and loaded.notes["bad"].data is None
    assert loaded.notes["fine"].errors == []
    found = lint.run(loaded, today=TODAY, only=["schema"])
    assert [(f.path, f.message) for f in found] == [("concepts/bad.md", "cannot read file")]


def test_read_note_text_returns_none_on_oserror(tmp_path: Path) -> None:
    assert notes.read_note_text(tmp_path / "missing.md") is None
    path = write(tmp_path, "a.md", "caf\xe9\n")
    path.write_bytes(b"caf\xe9\n")  # latin-1: decoded with replacement, never a raise
    assert notes.read_note_text(path) == "caf�\n"


# 2. phi.scan reads the files it was not given concurrently, same findings.


def _phi_tree(root: Path) -> Path:
    make_vault(root)
    for i in range(10):
        write(root, f"notes/n{i}.md", f"line one\nCall {phone()} today.\n")
        write(root, f"code/m{i}.py", "x = 1\n")
    write(root, "notes/clean.md", "nothing here\n")
    (root / "notes" / "bin.dat").write_bytes(b"\0" + f"Call {phone()}".encode())
    return root


def test_concurrent_phi_reads_give_sequential_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _phi_tree(tmp_path / "v").resolve()
    kwargs: dict[str, Any] = {"root": root, "settings": ScanSettings(), "allow": frozenset()}
    texts = {
        path: path.read_bytes().decode("utf-8", errors="replace")
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".labbrain" not in path.parts
    }
    # Everything from memory (no disk reads, no threads) is the sequential reference;
    # the NUL file is still re-read from disk and skipped as binary.
    expected = scan([root], texts=texts, **kwargs)
    assert len(expected) == 10
    monkeypatch.setattr(readpool, "read_workers", lambda: 2)
    monkeypatch.setattr(phi, "_read_outcome", _jittered(phi._read_outcome))
    assert scan([root], **kwargs) == expected
    some = dict(list(texts.items())[::2])
    assert scan([root], texts=some, **kwargs) == expected


def test_in_memory_texts_are_not_read_from_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _phi_tree(tmp_path / "v").resolve()
    given = root / "notes" / "n0.md"
    nul = root / "notes" / "nul.md"
    nul.write_bytes(b"a\0b\n")
    read: list[Path] = []
    real = phi._read_text

    def spy(path: Path) -> str | None:
        read.append(path)
        return real(path)

    monkeypatch.setattr(phi, "_read_text", spy)
    texts = {given: given.read_text(), nul: nul.read_text()}
    scan([root], root=root, settings=ScanSettings(), allow=frozenset(), texts=texts)
    assert given not in read
    assert nul in read  # a text with a NUL is re-read so the byte sniff decides
    assert len(read) == len(set(read))  # each file is read at most once


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read chmod 000 files")
def test_unreadable_and_outside_findings_with_concurrent_reads(tmp_path: Path) -> None:
    root = _phi_tree(tmp_path / "v").resolve()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    write(outside, "secret.md", f"Call {phone()}.\n")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    locked = root / "notes" / "locked.md"
    locked.write_text("x\n")
    locked.chmod(0)
    try:
        found = scan([root], root=root, settings=ScanSettings(), allow=frozenset())
    finally:
        locked.chmod(0o644)
    rows = [(f.path, f.rule, f.message) for f in found if f.rule == "phi-unreadable"]
    assert rows == [
        ("linked", "phi-unreadable", phi.OUTSIDE),
        ("notes/locked.md", "phi-unreadable", phi.UNREADABLE),
    ]


def test_ordered_map_keeps_order_and_bounds_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readpool, "read_workers", lambda: 3)
    started: list[int] = []
    lock = threading.Lock()

    def work(item: int) -> int:
        with lock:
            started.append(item)
        time.sleep(0.0005 * (item % 4))
        return item * 10

    out = []
    for consumed, value in enumerate(readpool.ordered_map(work, range(60)), start=1):
        time.sleep(0.001)  # a slow consumer
        with lock:
            assert len(started) - consumed <= 2 * 3  # never more than the window ahead
        out.append(value)
    assert out == [i * 10 for i in range(60)]


def test_closing_ordered_map_cancels_pending_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readpool, "read_workers", lambda: 2)
    calls: list[int] = []
    with closing(readpool.ordered_map(calls.append, range(1000))) as results:
        next(results)
    time.sleep(0.05)
    assert len(calls) <= 2 * 2 + 1


def test_read_workers_is_capped_at_eight() -> None:
    assert 1 <= readpool.read_workers() <= 8


def test_phi_scan_memory_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_vault(tmp_path / "v").resolve()
    size, count = 1 << 20, 48
    for i in range(count):
        (root / "raw").mkdir(exist_ok=True)
        (root / "raw" / f"big{i}.txt").write_bytes(b"plain text line\n" * (size // 16))
    monkeypatch.setattr(readpool, "read_workers", lambda: 2)

    def slow_scan(text: str, settings: ScanSettings) -> list[phi.PhiHit]:
        time.sleep(0.003)  # workers would race ahead of an unbounded consumer
        return []

    monkeypatch.setattr(phi, "scan_text", slow_scan)
    tracemalloc.start()
    try:
        scan([root], root=root, settings=ScanSettings(), allow=frozenset())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < count * size // 4  # window of 4 files, not all 48


@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt])
def test_phi_scan_stops_reading_when_the_scan_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[BaseException]
) -> None:
    root = make_vault(tmp_path / "v").resolve()
    for i in range(200):
        write(root, f"notes/n{i:03d}.md", "text\n")
    monkeypatch.setattr(readpool, "read_workers", lambda: 2)
    reads: list[Path] = []
    real = phi._read_text

    def counting(path: Path) -> str | None:
        reads.append(path)
        return real(path)

    def boom(text: str, settings: ScanSettings) -> list[phi.PhiHit]:
        raise error

    monkeypatch.setattr(phi, "_read_text", counting)
    monkeypatch.setattr(phi, "scan_text", boom)
    started = time.perf_counter()
    with pytest.raises(error):
        scan([root], root=root, settings=ScanSettings(), allow=frozenset())
    assert time.perf_counter() - started < 5
    time.sleep(0.05)  # reads already running may finish; none new may start
    assert len(reads) <= 2 * 2 + 1


# 3. The filename walk skips dot-directories.


def test_file_in_a_dot_directory_does_not_satisfy_a_bare_embed(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    body = body_for("decision", "![[hidden.png]] ![[shown.png]] ![[linked.png]]")
    write(root, "decisions/ADR-20261001-x.md", note_text("ADR-20261001-x", "decision", body=body))
    write(root, ".obsidian/attachments/hidden.png", "png")
    write(root, "raw/figs/shown.png", "png")
    (root / "raw" / "linked.png").symlink_to(root / "raw" / "figs" / "shown.png")
    ctx = lint.LintContext(vault=Vault.load(root), today=TODAY)
    messages = {f.message for f in lint.load_rules()["broken-link"].fn(ctx)}
    assert messages == {"body: missing file hidden.png"}
    assert "shown.png" in ctx.cache["link_rules.filenames"]
    assert "filenames" not in ctx.cache


def test_filename_walk_skips_git_entries_and_symlinked_dirs(tmp_path: Path) -> None:
    from labbrain.lint.rules.link_rules import _walk_filenames

    root = make_vault(tmp_path / "v")
    write(root, ".git", "gitdir: elsewhere\n")  # a worktree's gitfile
    write(root, "sub/.git", "gitdir: elsewhere\n")
    write(root, ".gitignore", "index.md\n")
    write(root, "a/b/deep.pdf", "pdf")
    other = tmp_path / "other"
    write(other, "outside.png", "png")
    (root / "linkdir").symlink_to(other, target_is_directory=True)
    (root / "broken.png").symlink_to(root / "nope.png")
    assert _walk_filenames(root) == {".gitignore", "deep.pdf"}


# 4. The "[[" fast path.


def test_wikilink_fast_path_keeps_inline_code_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    # Removing inline code can join "[" + "[": that line still links.
    assert wikilink_targets("[`x`[NOTE-1]]") == ["NOTE-1"]
    assert wikilink_targets("see `[[not-a-link]]` and [[real]]") == ["real"]

    class Boom:
        def sub(self, *args: Any) -> str:
            raise AssertionError("regex used on a line that cannot hold a link")

    monkeypatch.setattr(notes, "_INLINE_CODE_RE", Boom())
    assert wikilink_targets("plain prose, no brackets") == []
    assert wikilink_targets("a [single] bracket") == []
    assert wikilink_targets("code `x` but no brackets") == []


# 5. Body lines are computed once per note.


AGENT_CONCEPT = """---
id: c1
type: concept
title: T
created: 2026-10-01
updated: 2026-10-01
author: claude
status: active
sources: [EXP-20261001-a]
---
## For future agents

Read me first.

## Summary

AUROC reached 0.91 here.
See [[EXP-20261001-a]].

```
## Not a heading [[not-a-link]]
```

## Evidence

[[EXP-20261001-a]]

## Open questions

None.

## Related

None.
"""


def _reference_lines(note: notes.Note) -> list[tuple[int, str]]:
    out, in_fence = [], False
    for offset, line in enumerate(note.body.splitlines()):
        if notes._FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            out.append((note.body_line + offset, line))
    return out


def test_body_lines_are_computed_once_per_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = notes._scan_body_lines

    def counting(body: str, body_line: int) -> list[tuple[int, str]]:
        calls.append(body)
        return real(body, body_line)

    monkeypatch.setattr(notes, "_scan_body_lines", counting)
    root = make_vault(tmp_path, "project_name: T\nproject_slug: t\nprotected_data: false\n")
    write(root, "concepts/c1.md", AGENT_CONCEPT)
    loaded = Vault.load(root)
    note = loaded.notes["c1"]
    assert len(calls) == 1  # link harvest during parse
    assert list(iter_body_lines(note)) == _reference_lines(note)
    assert [t for _, t in h2_headings(note)][:2] == ["For future agents", "Summary"]
    assert future_agents_block(note) == ["Read me first."]
    assert index.summary(note) == "AUROC reached 0.91 here."
    findings = lint.run(loaded, today=TODAY, only=["undated-fact", "missing-section"])
    assert [f.rule for f in findings] == ["undated-fact"]
    assert len(calls) == 1


def test_body_line_cache_follows_a_replaced_body() -> None:
    note = parse_note_text(AGENT_CONCEPT, Path("concepts/c1.md"), "concepts/c1.md")
    assert list(iter_body_lines(note)) == _reference_lines(note)
    note.body = "## Only\n"
    assert list(iter_body_lines(note)) == [(note.body_line, "## Only")]
    assert "_body_lines" not in repr(note)
    fresh = parse_note_text(AGENT_CONCEPT, Path("concepts/c1.md"), "concepts/c1.md")
    other = parse_note_text(AGENT_CONCEPT, Path("concepts/c1.md"), "concepts/c1.md")
    other._body_lines = None
    assert fresh == other  # the cache takes no part in equality


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list chmod 000 directories")
def test_filename_walk_skips_unlistable_directories(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    write(root, "raw/ok.png", "png")
    write(root, "raw/locked/inside.png", "png")
    (root / "raw" / "locked").chmod(0)
    try:
        assert link_rules._walk_filenames(root) == {"ok.png"}
    finally:
        (root / "raw" / "locked").chmod(0o755)


def test_filename_walk_propagates_other_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_vault(tmp_path / "v")
    write(root, "raw/sub/a.png", "png")
    real = os.scandir

    def scandir(path: str) -> Any:
        if path.endswith("sub"):
            raise OSError(errno.EIO, "I/O error")
        return real(path)

    monkeypatch.setattr(link_rules.os, "scandir", scandir)
    with pytest.raises(OSError):
        link_rules._walk_filenames(root)


def test_entry_tests_follow_pathlib_error_rules() -> None:
    def raising(exc: OSError) -> Any:
        def test() -> bool:
            raise exc

        return test

    assert link_rules._entry_test(raising(FileNotFoundError(errno.ENOENT, "gone"))) is False
    assert link_rules._entry_test(raising(OSError(errno.ELOOP, "loop"))) is False
    with pytest.raises(PermissionError):
        link_rules._entry_test(raising(PermissionError(errno.EACCES, "denied")))
