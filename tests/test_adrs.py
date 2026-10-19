"""Engine ADRs are valid lab-brain decision notes."""

from __future__ import annotations

from pathlib import Path

from labbrain.lint.rules.schema_rules import check_note
from labbrain.notes import parse_note
from labbrain.vault import Config

REPO = Path(__file__).resolve().parents[1]
CONFIG = Config(
    project_name="lab-brain engine",
    project_slug="lab-brain",
    lab_members=["jorgebotas"],
    agents=["claude"],
)


def test_engine_adrs_are_valid_decision_notes() -> None:
    paths = sorted((REPO / "docs" / "decisions").glob("ADR-*.md"))
    assert len(paths) == 12
    for path in paths:
        findings = check_note(parse_note(path, REPO), CONFIG)
        assert findings == [], (path.name, [f.to_dict() for f in findings])
