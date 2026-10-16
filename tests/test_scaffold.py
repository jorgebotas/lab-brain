from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path

import pytest
from helpers import make_vault

from labbrain.layout import NOTE_TYPES, TYPE_FOLDERS
from labbrain.notes import update_frontmatter
from labbrain.scaffold import create
from labbrain.validate import validate_path
from labbrain.vault import load_config

NOW = datetime(2026, 10, 15, 12, 0)

EXPECTED_EXPERIMENT = """---
id: EXP-20261015-label-smoothing
type: experiment
title: Label smoothing
created: 2026-10-15
updated: 2026-10-15
author: alice
status: planned
tags: []
links: []
hypothesis:
protocol:
tracker:
code:
config_hash:
dataset:
metrics: []
supersedes:
superseded_by:
---
## Hypothesis

## Setup

## Results

## Interpretation

## Next
"""


def test_experiment_skeleton_text(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    path = create(
        root, load_config(root), "experiment", title="Label smoothing", author="alice", now=NOW
    )
    assert path == root / "experiments" / "EXP-20261015-label-smoothing.md"
    assert path.read_text() == EXPECTED_EXPERIMENT


@pytest.mark.parametrize("author", ["alice", "claude"])
@pytest.mark.parametrize("note_type", NOTE_TYPES)
def test_every_skeleton_validates_clean(vault_dir: Path, note_type: str, author: str) -> None:
    path = create(
        vault_dir,
        load_config(vault_dir),
        note_type,
        title="A new thing",
        author=author,
        now=NOW,
        first_author="Doe",
        year=2024,
    )
    assert path.parent == vault_dir / TYPE_FOLDERS[note_type]
    assert validate_path(path) == []


def test_protocol_skeleton_gets_next_version(vault_dir: Path) -> None:
    path = create(
        vault_dir, load_config(vault_dir), "protocol", title="Masked AUROC", author="alice", now=NOW
    )
    assert path.name == "EVAL-v3.md"
    assert "version: 3\n" in path.read_text()


def test_agent_skeleton_has_future_agents_block(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    path = create(root, load_config(root), "idea", title="Try it", author="claude", now=NOW)
    body = path.read_text().split("---\n", 2)[2]
    assert body.startswith("## For future agents\n\n<!-- ")


def test_skeleton_edits_are_one_line_diffs(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    path = create(root, load_config(root), "experiment", title="X", author="alice", now=NOW)
    before = path.read_text()
    update_frontmatter(path, {"status": "running"})
    changed = [
        line
        for line in difflib.ndiff(before.splitlines(), path.read_text().splitlines())
        if line.startswith(("+ ", "- "))
    ]
    assert changed == ["- status: planned", "+ status: running"]


YAML11_NON_STRING_TITLES = ["yes", "No", "on", "off", "null", "2026-10-15"]


@pytest.mark.parametrize("title", YAML11_NON_STRING_TITLES)
def test_yaml11_ambiguous_titles_validate_clean(vault_dir: Path, title: str) -> None:
    path = create(vault_dir, load_config(vault_dir), "idea", title=title, author="alice", now=NOW)
    assert f"title: '{title}'\n" in path.read_text()
    assert validate_path(path) == []
