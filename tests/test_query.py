from __future__ import annotations

import pytest
from helpers import FIXTURE

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
