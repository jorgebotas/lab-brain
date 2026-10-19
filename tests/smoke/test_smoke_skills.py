"""Headless smoke tests: the installed skills drive the engine end to end."""

from __future__ import annotations

from pathlib import Path

import pytest
from harness import run_skill

from labbrain.cli import main
from labbrain.experiments import config_diff, parent_run_ids, render_setup
from labbrain.notes import parse_note
from labbrain.trackers import get_adapter
from labbrain.vault import Vault, load_config

pytestmark = pytest.mark.smoke
PARENT = "EXP-20260910-label-smoothing"


def notes_in(folder: Path) -> set[Path]:
    return set(folder.glob("*.md"))


def test_idea(claude_bin: str, smoke_vault: Path) -> None:
    inbox = smoke_vault / "ideas" / "inbox"
    before = notes_in(inbox)
    run_skill(
        claude_bin, smoke_vault, "/lab-brain:idea Don't forget cosine warmup on the small model"
    )
    created = notes_in(inbox) - before
    assert len(created) == 1
    path = created.pop()
    assert "Don't forget" in path.read_text(encoding="utf-8")
    assert main(["--vault", str(smoke_vault), "validate", str(path)]) == 0
    assert main(["--vault", str(smoke_vault), "lint"]) == 0
    logs = "".join(p.read_text(encoding="utf-8") for p in (smoke_vault / "log").glob("*.md"))
    assert "idea:" in logs


def test_exp_log_with_parent(claude_bin: str, smoke_vault: Path) -> None:
    folder = smoke_vault / "experiments"
    before = notes_in(folder)
    run_skill(claude_bin, smoke_vault, f"/lab-brain:exp-log run-c1 run-c2 --parent {PARENT}")
    created = notes_in(folder) - before
    assert len(created) == 1
    path = created.pop()
    assert main(["--vault", str(smoke_vault), "validate", str(path)]) == 0
    data = parse_note(path, smoke_vault).data
    assert data is not None and data["status"] == "done"
    assert data["protocol"] == "EVAL-v2" and data["dataset"] == "DS-20260801-main-split"
    assert data["metrics"] and all(m["run_id"] and m["as_of"] for m in data["metrics"])
    config = load_config(smoke_vault)
    adapter = get_adapter(config, smoke_vault)
    parent = [r["config"] for r in adapter.fetch(parent_run_ids(Vault.load(smoke_vault), PARENT))]
    child = [r["config"] for r in adapter.fetch(["run-c1", "run-c2"])]
    expected = render_setup(config_diff(PARENT, parent, child, config.hash_ignore))
    text = path.read_text(encoding="utf-8")
    for row in expected.splitlines():
        if row.startswith("| "):
            assert row in text, row


def test_exp_log_refuses_done_without_protocol(claude_bin: str, smoke_vault: Path) -> None:
    folder = smoke_vault / "experiments"
    before = notes_in(folder)
    result = run_skill(claude_bin, smoke_vault, "/lab-brain:exp-log run-noproto")
    for path in notes_in(folder) - before:
        data = parse_note(path, smoke_vault).data
        assert data is None or data.get("status") != "done"
    assert "protocol" in str(result.get("result", "")).lower()
