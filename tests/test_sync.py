from __future__ import annotations

from datetime import date
from pathlib import Path

from fixtures.mutations import BASELINE, EVAL_V2, SMOOTHING, replace
from helpers import TODAY, body_for, make_vault, note_text, write

from labbrain import lint
from labbrain.sync import Change, apply, plan
from labbrain.vault import Vault

SUPERSEDES = (
    "links: [EXP-20260901-baseline]",
    "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
)


def test_valid_fixture_has_nothing_to_sync(vault_dir: Path) -> None:
    assert plan(Vault.load(vault_dir)) == ([], [])


def test_supersession_is_planned_applied_and_idempotent(vault_dir: Path) -> None:
    replace(vault_dir, SMOOTHING, *SUPERSEDES)
    vault = Vault.load(vault_dir)
    changes, conflicts = plan(vault)
    assert conflicts == []
    assert changes == [
        Change(
            "EXP-20260901-baseline",
            BASELINE,
            {"status": "superseded", "superseded_by": "EXP-20260910-label-smoothing"},
            "superseded by EXP-20260910-label-smoothing",
        )
    ]
    assert apply(vault, changes, TODAY) == [BASELINE]
    text = (vault_dir / BASELINE).read_text()
    assert "status: superseded\n" in text
    assert "superseded_by: EXP-20260910-label-smoothing\n" in text
    assert "updated: 2026-10-15\n" in text
    assert plan(Vault.load(vault_dir)) == ([], [])


def test_draft_protocol_referenced_by_done_experiment_is_frozen(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "status: frozen", "status: draft")
    changes, _ = plan(Vault.load(vault_dir))
    assert [(c.note_id, c.updates) for c in changes] == [("EVAL-v2", {"status": "frozen"})]


def test_conflicting_supersession_is_reported_not_written(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    old = note_text("ADR-20261001-old", "decision", status="accepted")
    write(root, "decisions/ADR-20261001-old.md", old)
    for name in ("a", "b"):
        write(
            root,
            f"decisions/ADR-20261002-{name}.md",
            note_text(f"ADR-20261002-{name}", "decision", supersedes="ADR-20261001-old"),
        )
    changes, conflicts = plan(Vault.load(root))
    assert changes == []
    assert [c.note_id for c in conflicts] == ["ADR-20261001-old"]
    assert "more than one" in conflicts[0].message


def test_already_superseded_by_someone_else(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(
        root,
        "decisions/ADR-20261001-old.md",
        note_text(
            "ADR-20261001-old", "decision", status="superseded", superseded_by="ADR-20261002-a"
        ),
    )
    write(
        root,
        "decisions/ADR-20261002-b.md",
        note_text(
            "ADR-20261002-b", "decision", supersedes="ADR-20261001-old", body=body_for("decision")
        ),
    )
    changes, conflicts = plan(Vault.load(root))
    assert changes == []
    assert "already superseded by ADR-20261002-a" in conflicts[0].message


def test_sync_pending_rule(vault_dir: Path) -> None:
    replace(vault_dir, SMOOTHING, *SUPERSEDES)
    findings = lint.run(Vault.load(vault_dir), today=date(2026, 10, 15), only=["sync-pending"])
    assert [(f.rule, f.severity, f.path) for f in findings] == [
        ("sync-pending", "warning", BASELINE)
    ]


def test_conflict_message_hides_a_value_that_is_not_id_shaped(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(
        root,
        "decisions/ADR-20261001-old.md",
        note_text(
            "ADR-20261001-old", "decision", status="superseded", superseded_by="Jane Doe, ward 4"
        ),
    )
    write(
        root,
        "decisions/ADR-20261002-b.md",
        note_text("ADR-20261002-b", "decision", supersedes="ADR-20261001-old"),
    )
    _, conflicts = plan(Vault.load(root))
    assert "Jane" not in conflicts[0].message
    assert "already superseded by <not a valid note ID>" in conflicts[0].message
