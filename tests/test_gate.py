"""M2 gate: the valid fixture is clean, and each mutation fires exactly its rule."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.mutations import MUTATIONS, Mutation
from helpers import TODAY, commit_all

from labbrain import lint
from labbrain.findings import Finding
from labbrain.vault import Vault


def run_lint(vault_dir: Path) -> list[Finding]:
    return lint.run(Vault.load(vault_dir), today=TODAY)


def test_valid_fixture_has_no_findings(vault_dir: Path) -> None:
    findings = run_lint(vault_dir)
    assert findings == [], [f.to_dict() for f in findings]


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda m: m.name)
def test_mutation_triggers_exactly_its_rule(vault_dir: Path, mutation: Mutation) -> None:
    mutation.apply(vault_dir)
    if not mutation.keep_index:
        (vault_dir / "index.md").unlink(missing_ok=True)
    if mutation.commit:
        commit_all(vault_dir, mutation.name)
    findings = run_lint(vault_dir)
    assert {f.rule for f in findings} == {mutation.rule}, [f.to_dict() for f in findings]


def test_every_rule_has_a_mutation() -> None:
    assert {m.rule for m in MUTATIONS} == set(lint.load_rules())
    assert len(lint.load_rules()) == 16
