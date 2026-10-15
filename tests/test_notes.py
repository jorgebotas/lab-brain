from __future__ import annotations

import difflib
import os
import random
import stat
from datetime import date
from pathlib import Path

import pytest

from labbrain.notes import (
    atomic_write,
    future_agents_block,
    h2_headings,
    parse_note_text,
    update_frontmatter,
    wikilink_targets,
)

SAMPLE = """---
id: EXP-20261013-label-smoothing
type: experiment
title: "Label smoothing vs. calibration"   # keep this comment
created: 2026-10-13
updated: 2026-10-13
author: alice
status: running
tags: [calibration]
links:
  - EXP-20261001-baseline
metrics:
  - {name: ece, value: 0.04, split: val, run_id: run-002, as_of: 2026-10-13}
---
## Hypothesis

See [[EXP-20261001-baseline|the baseline]] and [[DS-20260801-main#split]].

```text
[[NOT-A-LINK]]
```

Inline `[[ALSO-NOT]]` and a table cell [[EVAL-v3\\|v3]] and ![[raw/papers/x.pdf]].
"""


def parse(text: str, rel: str = "experiments/EXP-20261013-label-smoothing.md"):
    return parse_note_text(text, Path(rel), rel)


def test_parse_sample() -> None:
    note = parse(SAMPLE)
    assert note.errors == []
    assert note.model is not None
    assert note.body_line == 15
    assert note.stem == "EXP-20261013-label-smoothing"
    assert note.type == "experiment"
    assert note.get_str("title") == "Label smoothing vs. calibration"
    assert note.get_list("tags") == ["calibration"]
    assert note.get_date("created") == date(2026, 10, 13)


def test_links_from_frontmatter_and_body() -> None:
    note = parse(SAMPLE)
    assert [(r.target, r.line, r.field) for r in note.refs] == [
        ("EXP-20261001-baseline", 1, "links"),
        ("EXP-20261001-baseline", 17, "body"),
        ("DS-20260801-main", 17, "body"),
        ("EVAL-v3", 23, "body"),
        ("raw/papers/x.pdf", 23, "body"),
    ]
    assert [r.is_path for r in note.refs] == [False, False, False, False, True]


def test_wikilink_target_forms() -> None:
    line = "[[A]] [[B|x]] [[C\\|y]] [[D#h]] [[E^b]] ![[f/g.png]] `[[H]]` [[#local]]"
    assert wikilink_targets(line) == ["A", "B", "C", "D", "E", "f/g.png"]


def test_self_links_ignored() -> None:
    text = SAMPLE.replace("Inline", "Self [[EXP-20261013-label-smoothing]] inline")
    targets = [r.target for r in parse(text).refs]
    assert "EXP-20261013-label-smoothing" not in targets


def test_missing_frontmatter() -> None:
    note = parse("# just text\n", "concepts/stray.md")
    assert note.data is None
    assert note.errors == ["missing YAML frontmatter"]


def test_invalid_yaml_reports_line_only_and_keeps_body_links() -> None:
    secret = "48151623"
    note = parse(f"---\nid: x\nmrn: [{secret}\n---\nSee [[EXP-20261001-baseline]].\n")
    assert note.data is None
    assert len(note.errors) == 1
    assert note.errors[0].startswith("frontmatter is not valid YAML (line ")
    assert secret not in note.errors[0]
    assert [r.target for r in note.refs] == ["EXP-20261001-baseline"]


def test_non_mapping_frontmatter() -> None:
    assert parse("---\n- a\n- b\n---\n").errors == ["frontmatter must be a YAML mapping"]


def test_model_failure_still_harvests_frontmatter_links() -> None:
    note = parse(SAMPLE.replace("status: running", "status: bogus"))
    assert note.model is None
    assert note.errors and note.errors[0].startswith("status:")
    assert "EXP-20261001-baseline" in [r.target for r in note.refs if r.field == "links"]


def test_h2_headings_skip_code_fences() -> None:
    assert h2_headings(parse(SAMPLE)) == [(15, "Hypothesis")]


def test_future_agents_block() -> None:
    head = "---\nid: x\n---\n"
    note = parse(head + "\n## For future agents\nline one\n\nline two\n\n## Summary\nbody\n")
    assert future_agents_block(note) == ["line one", "line two"]
    assert future_agents_block(parse(head + "## Summary\nbody\n")) is None


def test_update_frontmatter_is_a_one_line_diff(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(SAMPLE)
    assert update_frontmatter(path, {"status": "done"}) is True
    changed = [
        line
        for line in difflib.ndiff(SAMPLE.splitlines(), path.read_text().splitlines())
        if line.startswith(("+ ", "- "))
    ]
    assert changed == ["- status: running", "+ status: done"]


def test_update_frontmatter_noop_and_new_key(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(SAMPLE)
    assert update_frontmatter(path, {"status": "running"}) is False
    assert path.read_text() == SAMPLE
    assert update_frontmatter(path, {"superseded_by": "EXP-20261014-x"}) is True
    new = path.read_text()
    assert "superseded_by: EXP-20261014-x\n---\n## Hypothesis" in new
    assert new.replace("superseded_by: EXP-20261014-x\n", "") == SAMPLE


def test_update_frontmatter_writes_dates(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(SAMPLE)
    update_frontmatter(path, {"updated": date(2026, 10, 15)})
    assert "updated: 2026-10-15\n" in path.read_text()
    assert list(tmp_path.iterdir()) == [path]  # no temp files left behind


def _changed_lines(before: str, after: str) -> list[str]:
    return [
        line
        for line in difflib.ndiff(before.splitlines(), after.splitlines())
        if line.startswith(("+ ", "- "))
    ]


def _synthetic_value(seed: int) -> str:
    return str(random.Random(seed).randrange(10**7, 10**8))


def test_update_frontmatter_preserves_crlf(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    original = SAMPLE.replace("\n", "\r\n").encode()
    path.write_bytes(original)
    assert update_frontmatter(path, {"status": "done"}) is True
    new = path.read_bytes()
    before = original.decode().split("\r\n")
    after = new.decode().split("\r\n")
    assert all("\n" not in line for line in after)  # every line still ends in CRLF
    assert _changed_lines("\n".join(before), "\n".join(after)) == [
        "- status: running",
        "+ status: done",
    ]


def test_update_frontmatter_keeps_file_mode(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(SAMPLE)
    path.chmod(0o644)
    assert update_frontmatter(path, {"status": "done"}) is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_atomic_write_new_file_uses_umask(tmp_path: Path) -> None:
    umask = os.umask(0o022)
    try:
        path = tmp_path / "sub" / "new.md"
        atomic_write(path, "x\n")
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
        os.umask(0o027)
        other = tmp_path / "other.md"
        atomic_write(other, "y\n")
        assert stat.S_IMODE(other.stat().st_mode) == 0o640
    finally:
        os.umask(umask)


def test_duplicate_key_is_a_read_error_without_key_or_value() -> None:
    first, second = _synthetic_value(1), _synthetic_value(2)
    note = parse(
        f"---\nid: x\nsecret_field: {first}\nsecret_field: {second}\n---\nSee [[EXP-1]].\n"
    )
    assert note.data is None
    assert note.errors == ["frontmatter has a duplicate key (line 4)"]
    assert note.error_line == 4
    assert [r.target for r in note.refs] == ["EXP-1"]


def test_nested_duplicate_key_is_a_read_error() -> None:
    note = parse("---\nid: x\nmetrics:\n  - {name: a, name: b}\n---\n")
    assert note.errors == ["frontmatter has a duplicate key (line 4)"]


def test_merge_keys_are_not_duplicates() -> None:
    note = parse("---\nbase: &b {a: 1}\nderived:\n  <<: *b\n  a: 2\n---\n")
    assert note.data is not None
    assert note.data["derived"] == {"a": 2}


def test_update_frontmatter_load_error_has_line_only(tmp_path: Path) -> None:
    value = _synthetic_value(3)
    path = tmp_path / "note.md"
    text = f"---\nid: x\nsecret_field: {value}\nsecret_field: {value}\n---\nbody\n"
    path.write_text(text)
    with pytest.raises(ValueError) as info:
        update_frontmatter(path, {"status": "done"})
    message = str(info.value)
    assert message == "note.md: frontmatter cannot be updated (line 4)"
    assert value not in message and "secret_field" not in message
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert path.read_text() == text


def test_update_frontmatter_keeps_zero_offset_lists(tmp_path: Path) -> None:
    text = SAMPLE.replace("links:\n  - EXP-20261001-baseline\n", "links:\n- A\n- B\n")
    text = text.replace("metrics:\n  - {", "metrics:\n- {")
    assert "links:\n- A\n- B\nmetrics:\n- {" in text
    path = tmp_path / "note.md"
    path.write_text(text)
    assert update_frontmatter(path, {"status": "done"}) is True
    assert _changed_lines(text, path.read_text()) == ["- status: running", "+ status: done"]


def test_update_frontmatter_keeps_zero_offset_block_mappings(tmp_path: Path) -> None:
    text = "---\nid: x\nstatus: running\nmetrics:\n- name: ece\n  value: 0.04\n---\nbody\n"
    path = tmp_path / "note.md"
    path.write_text(text)
    assert update_frontmatter(path, {"status": "done"}) is True
    assert _changed_lines(text, path.read_text()) == ["- status: running", "+ status: done"]
