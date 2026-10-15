"""broken-link and orphan."""

from __future__ import annotations

import errno
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path

from labbrain.findings import ERROR, WARNING, Finding
from labbrain.lint import LintContext, rule

ORPHAN_EXEMPT = frozenset({"idea", "handoff"})

# Note IDs identify notes and may be echoed; any other unresolved target is arbitrary
# text (possibly a frontmatter value) and is never rendered.
_ECHOABLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$")
_NOT_AN_ID = "<not a valid note ID>"


def _render(target: str) -> str:
    return target if _ECHOABLE_RE.match(target) else _NOT_AN_ID


_FILENAMES_KEY = "link_rules.filenames"


# Errors pathlib treats as "does not exist" (Python 3.11 pathlib._IGNORED_ERRNOS).
_MISSING_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP})


def _entry_test(test: Callable[[], bool]) -> bool:
    """Run a DirEntry type test like pathlib: a missing target is False, other errors raise."""
    try:
        return test()
    except OSError as exc:
        if exc.errno in _MISSING_ERRNOS:
            return False
        raise


def _walk_filenames(root: Path) -> set[str]:
    """Names of regular files (or symlinks to them) under `root`.

    Descends only real directories whose name does not start with a dot (.git,
    .obsidian, .labbrain, ...), and never collects an entry named `.git`. Like the
    `rglob` it replaces, a directory that cannot be listed for lack of permission is
    skipped; any other error propagates.
    """
    names: set[str] = set()
    stack = [os.fspath(root)]
    while stack:
        here = stack.pop()
        try:
            with os.scandir(here) as listing:
                entries = list(listing)
        except PermissionError:
            continue
        for entry in entries:
            if entry.name == ".git":
                continue
            if _entry_test(lambda e=entry: e.is_dir(follow_symlinks=False)):
                if not entry.name.startswith("."):
                    stack.append(entry.path)
            elif _entry_test(entry.is_file):  # follows symlinks, like Path.is_file
                names.add(entry.name)
    return names


def _vault_filenames(ctx: LintContext) -> set[str]:
    if _FILENAMES_KEY not in ctx.cache:
        ctx.cache[_FILENAMES_KEY] = _walk_filenames(ctx.vault.root)
    return ctx.cache[_FILENAMES_KEY]


def _path_exists(ctx: LintContext, target: str) -> bool:
    if "/" in target:
        return (ctx.vault.root / target).exists()
    return target in _vault_filenames(ctx)  # Obsidian resolves bare filenames anywhere


@rule("broken-link", ERROR, "Every wikilink and ID-bearing frontmatter value resolves")
def broken_link(ctx: LintContext) -> Iterator[Finding]:
    for note in ctx.vault.all_notes():
        for ref in note.refs:
            # Only body wikilinks may name files; every frontmatter value must be a note ID.
            if ref.field == "body" and ref.is_path:
                if not _path_exists(ctx, ref.target):
                    message = f"{ref.field}: missing file {_render(ref.target)}"
                    yield Finding(note.rel, ref.line, "broken-link", ERROR, message)
            elif ref.target not in ctx.vault.notes:
                message = f"{ref.field}: unresolved link [[{_render(ref.target)}]]"
                yield Finding(note.rel, ref.line, "broken-link", ERROR, message)


@rule("orphan", WARNING, "Note with no inbound links (ideas and handoffs exempt)")
def orphan(ctx: LintContext) -> Iterator[Finding]:
    for stem, note in ctx.vault.notes.items():
        if note.type is None or note.type in ORPHAN_EXEMPT:
            continue
        if not ctx.vault.inbound.get(stem):
            yield Finding(note.rel, 1, "orphan", WARNING, "no inbound links")
