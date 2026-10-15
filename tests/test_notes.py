from __future__ import annotations

import difflib
from datetime import date
from pathlib import Path

from labbrain.notes import (
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
