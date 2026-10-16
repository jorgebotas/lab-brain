from __future__ import annotations

import random
from pathlib import Path

import pytest
from helpers import FIXTURE, make_vault, note_text, write

from labbrain.query import links, list_notes
from labbrain.vault import Vault


def test_list_filters() -> None:
    vault = Vault.load(FIXTURE)
    assert [r["id"] for r in list_notes(vault, note_type="experiment")] == [
        "EXP-20260901-baseline",
        "EXP-20260910-label-smoothing",
    ]
    assert [r["id"] for r in list_notes(vault, note_type="idea", status="open")] == [
        "IDEA-20261010-smoothing-schedule"
    ]
    assert [r["id"] for r in list_notes(vault, tag="evaluation")] == [
        "ADR-20260905-adopt-eval-v2",
        "EVAL-v1",
        "EVAL-v2",
    ]
    row = list_notes(vault, note_type="claim")[0]
    assert row == {
        "id": "CLM-20261001-median-auroc",
        "type": "claim",
        "status": "supported",
        "title": "Median AUROC of the baseline",
        "created": "2026-10-01",
        "path": "claims/CLM-20261001-median-auroc.md",
    }


def test_links() -> None:
    vault = Vault.load(FIXTURE)
    assert links(vault, "CLM-20261001-median-auroc") == {
        "id": "CLM-20261001-median-auroc",
        "in": ["HO-20261014-1420-claude", "label-smoothing-calibration"],
        "out": ["EVAL-v2", "EXP-20260901-baseline"],
    }
    with pytest.raises(KeyError):
        links(vault, "nope")


def probe_vault(root: Path) -> tuple[Path, list[str]]:
    """A vault whose links hold identifier-like free text; returns it and the secrets."""
    rng = random.Random(11)
    mrn = str(rng.randrange(10_000_000, 99_999_999))
    phone = f"{rng.randrange(200, 999)}-{rng.randrange(1000, 9999)}"
    make_vault(root)
    write(root, "concepts/target.md", note_text("target", "concept"))
    write(
        root,
        "concepts/probe.md",
        note_text(
            "probe",
            "concept",
            body="## Definition\n\n[[target]] and [[Jane Q Doe " + phone + "]]\n\n"
            "## For future agents\n\nText.\n",
            links=["target", f"Patient MRN {mrn}", "EXP-20990101-not-there"],
        ),
    )
    return root, [mrn, phone, "Jane"]


def test_links_never_echo_free_text_targets(tmp_path: Path) -> None:
    root, secrets = probe_vault(tmp_path / "v")
    data = links(Vault.load(root), "probe")
    assert data["out"] == ["<not a valid note ID>", "EXP-20990101-not-there", "target"]
    assert links(Vault.load(root), "target")["in"] == ["probe"]
    assert not any(secret in str(data) for secret in secrets)


def test_links_never_echo_identifier_shaped_targets(tmp_path: Path) -> None:
    rng = random.Random(29)
    ssn = f"{rng.randrange(100, 899)}-{rng.randrange(10, 99)}-{rng.randrange(1000, 9999)}"
    phone = f"{rng.randrange(200, 999)}-{rng.randrange(200, 999)}-{rng.randrange(1000, 9999)}"
    mrn = f"MRN-{rng.randrange(10**7, 10**8)}"
    root = make_vault(tmp_path)
    write(root, "concepts/probe.md", note_text("probe", "concept", links=[ssn, phone, mrn]))
    data = links(Vault.load(root), "probe")
    assert data["out"] == ["<not a valid note ID>"]
    assert not any(secret in str(data) for secret in (ssn, phone, mrn))
