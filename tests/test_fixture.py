from __future__ import annotations

from pathlib import Path

from helpers import FIXTURE, git

from labbrain.notes import dump_frontmatter, future_agents_block, rt_yaml, split_frontmatter
from labbrain.vault import Vault

EXPECTED = {
    "EXP-20260901-baseline",
    "EXP-20260910-label-smoothing",
    "EVAL-v1",
    "EVAL-v2",
    "DS-20260801-main-split",
    "CLM-20261001-median-auroc",
    "label-smoothing-calibration",
    "ADR-20260905-adopt-eval-v2",
    "LIT-szegedy2016-rethinking",
    "IDEA-20261010-smoothing-schedule",
    "IDEA-20260912-smoothing-helps",
    "HO-20261014-1420-claude",
}


def test_fixture_notes_parse_cleanly() -> None:
    vault = Vault.load(FIXTURE)
    assert set(vault.notes) == EXPECTED
    assert vault.duplicates == {}
    for note in vault.all_notes():
        assert note.errors == [], note.rel


def test_every_linkable_note_has_two_inbound_links() -> None:
    """Harness invariant: a mutation that removes one link never creates an orphan."""
    vault = Vault.load(FIXTURE)
    for stem, note in vault.notes.items():
        if note.type not in ("idea", "handoff"):
            assert len(vault.inbound.get(stem, set())) >= 2, stem


def test_agent_notes_open_with_future_agents_block() -> None:
    vault = Vault.load(FIXTURE)
    for note in vault.all_notes():
        if note.get_str("author") == "claude":
            block = future_agents_block(note)
            assert block and len(block) <= 3, note.rel


def test_fixture_frontmatter_round_trips_byte_for_byte() -> None:
    for path in sorted(FIXTURE.rglob("*.md")):
        fm, _, _ = split_frontmatter(path.read_text())
        if fm is not None:
            assert dump_frontmatter(rt_yaml().load(fm)) == fm, path.name


def test_vault_dir_is_a_clean_git_copy(vault_dir: Path) -> None:
    assert (vault_dir / ".git").is_dir()
    assert git(vault_dir, "status", "--porcelain") == ""
