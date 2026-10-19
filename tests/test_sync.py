from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import pytest
from fixtures.mutations import BASELINE, EVAL_V2, SMOOTHING, replace
from helpers import TODAY, body_for, make_vault, note_text, write

from labbrain import lint
from labbrain.notes import render_note
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
    assert apply(vault, changes, TODAY) == ([BASELINE], [])
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
            note_text(
                f"ADR-20261002-{name}",
                "decision",
                status="accepted",
                supersedes="ADR-20261001-old",
            ),
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
            "ADR-20261002-b",
            "decision",
            status="accepted",
            supersedes="ADR-20261001-old",
            body=body_for("decision"),
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
        note_text("ADR-20261002-b", "decision", status="accepted", supersedes="ADR-20261001-old"),
    )
    _, conflicts = plan(Vault.load(root))
    assert "Jane" not in conflicts[0].message
    assert "already superseded by <not a valid note ID>" in conflicts[0].message


def test_protocol_target_cannot_be_superseded(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(
        root,
        "protocols/EVAL-v1.md",
        note_text("EVAL-v1", "protocol", status="draft", body=body_for("protocol")),
    )
    write(
        root,
        "decisions/ADR-20261002-b.md",
        note_text(
            "ADR-20261002-b",
            "decision",
            status="accepted",
            supersedes="EVAL-v1",
            body=body_for("decision"),
        ),
    )
    vault = Vault.load(root)
    changes, conflicts = plan(vault)
    assert changes == []
    assert [(c.note_id, c.rel) for c in conflicts] == [("EVAL-v1", "protocols/EVAL-v1.md")]
    assert "EVAL-v1 is a protocol and cannot be superseded" in conflicts[0].message
    findings = lint.run(vault, today=TODAY, only=["sync-pending"])
    assert [(f.severity, f.path) for f in findings] == [("error", "protocols/EVAL-v1.md")]


def test_target_of_unknown_type_cannot_be_superseded(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    old = render_note({"id": "ADR-20261001-old", "type": "Jane Doe", "status": "accepted"}, "")
    write(root, "decisions/ADR-20261001-old.md", old)
    write(
        root,
        "decisions/ADR-20261002-b.md",
        note_text("ADR-20261002-b", "decision", status="accepted", supersedes="ADR-20261001-old"),
    )
    changes, conflicts = plan(Vault.load(root))
    assert changes == []
    assert [c.note_id for c in conflicts] == ["ADR-20261001-old"]
    assert "cannot be superseded" in conflicts[0].message
    assert "Jane" not in conflicts[0].message


def test_conflict_message_hides_an_identifier_shaped_value(tmp_path: Path) -> None:
    rng = random.Random(31)
    ssn = f"{rng.randrange(100, 899)}-{rng.randrange(10, 99)}-{rng.randrange(1000, 9999)}"
    root = make_vault(tmp_path)
    write(
        root,
        "decisions/ADR-20261001-old.md",
        note_text("ADR-20261001-old", "decision", status="superseded", superseded_by=ssn),
    )
    write(
        root,
        "decisions/ADR-20261002-b.md",
        note_text("ADR-20261002-b", "decision", status="accepted", supersedes="ADR-20261001-old"),
    )
    _, conflicts = plan(Vault.load(root))
    assert ssn not in conflicts[0].message
    assert "already superseded by <not a valid note ID>" in conflicts[0].message


def test_self_supersession_is_a_conflict(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(
        root,
        "decisions/ADR-20261001-self.md",
        note_text(
            "ADR-20261001-self", "decision", status="accepted", supersedes="ADR-20261001-self"
        ),
    )
    changes, conflicts = plan(Vault.load(root))
    assert changes == []
    assert [(c.note_id, c.message) for c in conflicts] == [
        ("ADR-20261001-self", "ADR-20261001-self claims to supersede itself")
    ]


def test_conflict_grammar_for_types_starting_with_a_vowel(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "ideas/inbox/IDEA-20261001-x.md", note_text("IDEA-20261001-x", "idea"))
    write(
        root,
        "decisions/ADR-20261002-b.md",
        note_text("ADR-20261002-b", "decision", status="accepted", supersedes="IDEA-20261001-x"),
    )
    _, conflicts = plan(Vault.load(root))
    assert conflicts[0].message == "IDEA-20261001-x is an idea and cannot be superseded"


def test_apply_reports_a_failed_write_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import labbrain.sync as sync_module

    real = sync_module.update_frontmatter

    def flaky(path: Path, updates: dict) -> bool:
        if path.name.startswith("ADR-20261001-a"):
            raise ValueError(f"{path.name}: frontmatter cannot be updated (line 3)")
        return real(path, updates)

    monkeypatch.setattr(sync_module, "update_frontmatter", flaky)
    root = make_vault(tmp_path)
    for old, new in (("a", "c"), ("b", "d")):
        write(
            root,
            f"decisions/ADR-20261001-{old}.md",
            note_text(f"ADR-20261001-{old}", "decision", status="accepted"),
        )
        write(
            root,
            f"decisions/ADR-20261002-{new}.md",
            note_text(
                f"ADR-20261002-{new}",
                "decision",
                status="accepted",
                supersedes=f"ADR-20261001-{old}",
            ),
        )
    vault = Vault.load(root)
    written, failed = apply(vault, plan(vault)[0], TODAY)
    assert written == ["decisions/ADR-20261001-b.md"]
    assert [(c.note_id, c.rel, c.message) for c in failed] == [
        (
            "ADR-20261001-a",
            "decisions/ADR-20261001-a.md",
            "could not write: ADR-20261001-a.md: frontmatter cannot be updated (line 3)",
        )
    ]


def test_a_note_that_is_not_utf8_is_reported_without_its_bytes(tmp_path: Path) -> None:
    from labbrain.vault import load_config

    root = make_vault(tmp_path / "v")
    path = write(root, "decisions/x.md", "---\nid: x\nstatus: accepted\n---\ncaf")
    path.write_bytes(path.read_bytes() + b"\xe9\n")
    vault = Vault.load(root, load_config(root))
    change = Change("x", "decisions/x.md", {"status": "superseded"}, "superseded by y")
    written, failed = apply(vault, [change], date(2026, 10, 15))
    assert written == []
    assert [f.message for f in failed] == ["could not write: file is not valid UTF-8"]


@pytest.mark.parametrize(
    ("note_type", "folder", "prefix", "pending", "in_force", "old_status"),
    [
        ("decision", "decisions", "ADR", "proposed", "accepted", "accepted"),
        ("experiment", "experiments", "EXP", "planned", "running", "done"),
    ],
)
def test_a_successor_supersedes_only_once_in_force(
    tmp_path: Path,
    note_type: str,
    folder: str,
    prefix: str,
    pending: str,
    in_force: str,
    old_status: str,
) -> None:
    root = make_vault(tmp_path)
    old_id, new_id = f"{prefix}-20261001-old", f"{prefix}-20261002-new"
    extra = {"dataset": "DS-20261001-d"} if note_type == "experiment" else {}
    write(root, f"{folder}/{old_id}.md", note_text(old_id, note_type, status=old_status, **extra))
    new_path = write(
        root,
        f"{folder}/{new_id}.md",
        note_text(new_id, note_type, status=pending, supersedes=old_id),
    )
    assert plan(Vault.load(root)) == ([], [])
    new_path.write_text(note_text(new_id, note_type, status=in_force, supersedes=old_id))
    changes, conflicts = plan(Vault.load(root))
    assert conflicts == []
    assert [(c.note_id, c.updates) for c in changes] == [
        (old_id, {"status": "superseded", "superseded_by": new_id})
    ]
