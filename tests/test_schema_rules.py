from __future__ import annotations

from pathlib import Path

from helpers import body_for, make_vault, note_text, write

from labbrain.lint.rules.schema_rules import check_note
from labbrain.notes import parse_note
from labbrain.vault import load_config

REL = "decisions/ADR-20261001-x.md"


def check(root: Path, rel: str = REL) -> list[tuple[str, str, str]]:
    note = parse_note(root / rel, root)
    return [(f.rule, f.severity, f.message) for f in check_note(note, load_config(root))]


def test_valid_note_has_no_findings(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-x", "decision"))
    assert check(root) == []


def test_id_must_match_filename(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-y", "decision"))
    assert check(root) == [("schema", "error", "id does not match the filename")]


def test_filename_must_be_a_valid_id(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "decisions/adr-one.md", note_text("adr-one", "decision"))
    assert check(root, "decisions/adr-one.md") == [
        ("schema", "error", "filename is not a valid decision ID")
    ]


def test_author_must_be_member_or_agent(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-x", "decision", author="mallory"))
    assert check(root) == [("schema", "error", "author is not in lab_members or agents")]


def test_model_errors_are_schema_errors(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-x", "decision", status="bogus"))
    findings = check(root)
    assert len(findings) == 1
    assert findings[0][:2] == ("schema", "error")
    assert findings[0][2].startswith("status:")


def test_missing_section(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    body = body_for("decision").replace("## Consequences\n\nText.\n\n", "")
    write(root, REL, note_text("ADR-20261001-x", "decision", body=body))
    assert check(root) == [
        ("missing-section", "warning", "missing required section: ## Consequences")
    ]


def test_agent_note_needs_future_agents_block(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-x", "decision", author="claude"))
    assert check(root) == [
        (
            "missing-section",
            "warning",
            "agent-authored note must start with '## For future agents'",
        )
    ]


def test_agent_block_at_most_three_lines(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    four = "## For future agents\n\na\nb\nc\nd\n\n" + body_for("decision")
    write(root, REL, note_text("ADR-20261001-x", "decision", author="claude", body=four))
    assert check(root) == [
        ("missing-section", "warning", "'## For future agents' block has more than 3 lines")
    ]
    three = "## For future agents\n\na\nb\nc\n\n" + body_for("decision")
    write(root, REL, note_text("ADR-20261001-x", "decision", author="claude", body=three))
    assert check(root) == []


def test_stray_file_without_frontmatter(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "concepts/stray.md", "just text\n")
    assert check(root, "concepts/stray.md") == [("schema", "error", "missing YAML frontmatter")]
