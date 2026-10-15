from __future__ import annotations

from pathlib import Path

from fixtures.mutations import BASELINE, CLAIM, EVAL_V1, EVAL_V2, SMOOTHING, replace
from helpers import TODAY

from labbrain import lint
from labbrain.lint.rules.protocol_rules import comparable
from labbrain.vault import Vault


def fired(root: Path, *rules: str) -> list[tuple[str, str]]:
    return [(f.rule, f.path) for f in lint.run(Vault.load(root), today=TODAY, only=rules)]


def test_comparable_is_reflexive_and_symmetric_not_transitive(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "comparable_with: []", "comparable_with: [EVAL-v1]")
    vault = Vault.load(vault_dir)
    assert comparable("EVAL-v2", "EVAL-v2", vault)
    assert comparable("EVAL-v2", "EVAL-v1", vault)
    assert comparable("EVAL-v1", "EVAL-v2", vault)  # symmetric: v1 is frozen, cannot list v2
    assert not comparable("EVAL-v1", "EVAL-v3", vault)


def test_cross_protocol_respects_declared_comparability(vault_dir: Path) -> None:
    replace(vault_dir, CLAIM, "protocol: EVAL-v2", "protocol: EVAL-v1")
    assert fired(vault_dir, "cross-protocol") == [("cross-protocol", CLAIM)]
    replace(vault_dir, EVAL_V1, "comparable_with: []", "comparable_with: [EVAL-v2]")
    assert fired(vault_dir, "cross-protocol") == []


def test_cross_protocol_skips_evidence_without_protocol(vault_dir: Path) -> None:
    replace(vault_dir, CLAIM, "protocol: EVAL-v2", "protocol: EVAL-v1")
    replace(vault_dir, BASELINE, "protocol: EVAL-v2\n", "")
    assert fired(vault_dir, "cross-protocol") == []


def test_duplicate_config_ignores_supersession_pairs(vault_dir: Path) -> None:
    hash_line = (
        'config_hash: "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"'
    )
    baseline_hash = (
        'config_hash: "sha256:3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b"'
    )
    replace(vault_dir, SMOOTHING, hash_line, baseline_hash)
    assert sorted(fired(vault_dir, "duplicate-config")) == [
        ("duplicate-config", BASELINE),
        ("duplicate-config", SMOOTHING),
    ]
    replace(
        vault_dir,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )
    assert fired(vault_dir, "duplicate-config") == []
