from __future__ import annotations

import shutil
from pathlib import Path

from fixtures.mutations import BASELINE, EVAL_V2, IDEA_OPEN, SMOOTHING, replace
from helpers import FIXTURE, TODAY, commit_all, git

from labbrain import lint
from labbrain.sync import apply, plan
from labbrain.vault import Vault


def frozen(root: Path, base: str = "HEAD") -> list[tuple[str, str, str]]:
    findings = lint.run(Vault.load(root), today=TODAY, base=base, only=["frozen-edit"])
    return [(f.severity, f.path, f.message) for f in findings]


def test_inserting_a_section_is_allowed(vault_dir: Path) -> None:
    with (vault_dir / BASELINE).open("a") as handle:
        handle.write("\n## Postmortem\n\nNothing to add.\n")
    assert frozen(vault_dir) == []


def test_idea_move_with_allowed_transition_is_clean(vault_dir: Path) -> None:
    src = vault_dir / IDEA_OPEN
    dest = vault_dir / "ideas" / "archive" / src.name
    text = src.read_text().replace(
        "status: open", "status: consolidated\nconsolidated_into: label-smoothing-calibration"
    )
    dest.write_text(text)
    src.unlink()
    (vault_dir / "index.md").unlink()
    findings = lint.run(Vault.load(vault_dir), today=TODAY)
    assert findings == [], [f.to_dict() for f in findings]


def test_sync_output_never_trips_frozen_edit(vault_dir: Path) -> None:
    replace(
        vault_dir,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )
    commit_all(vault_dir, "supersede baseline")
    vault = Vault.load(vault_dir)
    apply(vault, plan(vault)[0], TODAY)
    findings = lint.run(Vault.load(vault_dir), today=TODAY, only=["frozen-edit", "sync-pending"])
    assert findings == []


def test_draft_protocol_referenced_by_done_experiment_is_frozen(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "status: frozen", "status: draft")
    commit_all(vault_dir, "draft protocol")
    replace(vault_dir, EVAL_V2, "ECE depends on the bin count.", "ECE is robust.")
    assert [m for _, _, m in frozen(vault_dir)] == [
        "existing body lines were modified or deleted; only insertions are allowed"
    ]


def test_draft_to_frozen_transition_is_allowed(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "status: frozen", "status: draft")
    commit_all(vault_dir, "draft protocol")
    replace(vault_dir, EVAL_V2, "status: draft", "status: frozen")
    assert frozen(vault_dir) == []


def test_base_option_catches_committed_violations(vault_dir: Path) -> None:
    replace(vault_dir, BASELINE, "Try label smoothing.", "Try something else.")
    commit_all(vault_dir, "sneaky rewrite")
    assert frozen(vault_dir) == []
    assert [p for _, p, _ in frozen(vault_dir, base="HEAD~1")] == [BASELINE]


def test_skipped_outside_git_and_for_unknown_base(tmp_path: Path, vault_dir: Path) -> None:
    plain = tmp_path / "plain"
    shutil.copytree(FIXTURE, plain)
    assert frozen(plain) == [("info", "", "not a git repository; frozen-edit skipped")]
    assert frozen(vault_dir, base="no-such-ref") == [
        ("info", "", "base revision no-such-ref not found; frozen-edit skipped")
    ]


def test_subfolder_vault_ignores_code_changes(tmp_path: Path) -> None:
    repo = tmp_path / "code"
    repo.mkdir()
    (repo / "train.py").write_text("x = 1\n")
    shutil.copytree(FIXTURE, repo / "brain")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo)
    (repo / "train.py").write_text("x = 2\n")
    brain = repo / "brain"
    assert frozen(brain) == []
    replace(brain, BASELINE, "status: done", "status: running")
    assert frozen(brain) == [
        ("error", BASELINE, "status change done → running is not allowed on a frozen experiment")
    ]


def test_messages_never_echo_invalid_status_or_unknown_keys(vault_dir: Path) -> None:
    replace(vault_dir, BASELINE, "status: done", "status: Jane Roe 555\nRoe-notes: x")
    assert frozen(vault_dir) == [
        ("error", BASELINE, "frozen field <unknown field> changed"),
        (
            "error",
            BASELINE,
            "status change done → <invalid status> is not allowed on a frozen experiment",
        ),
    ]
