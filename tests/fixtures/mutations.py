"""Named mutations of the valid fixture, one or more per lint rule.

Each mutation changes the vault so that exactly its declared rule fires. Its
docstring says why no other rule fires; reviewers check that claim. Harness
(tests/test_gate.py): index.md is deleted unless keep_index; the mutation is
committed unless commit=False (only frozen-edit mutations stay uncommitted).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

BASELINE = "experiments/EXP-20260901-baseline.md"
SMOOTHING = "experiments/EXP-20260910-label-smoothing.md"
CLAIM = "claims/CLM-20261001-median-auroc.md"
CONCEPT = "concepts/label-smoothing-calibration.md"
DECISION = "decisions/ADR-20260905-adopt-eval-v2.md"
LITERATURE = "literature/LIT-szegedy2016-rethinking.md"
DATASET = "datasets/DS-20260801-main-split.md"
EVAL_V1 = "protocols/EVAL-v1.md"
EVAL_V2 = "protocols/EVAL-v2.md"
IDEA_OPEN = "ideas/inbox/IDEA-20261010-smoothing-schedule.md"
HANDOFF = "handoffs/HO-20261014-1420-claude.md"
RAW_PAPER = "raw/papers/szegedy2016-rethinking.txt"


@dataclass(frozen=True)
class Mutation:
    name: str
    rule: str
    apply: Callable[[Path], None]
    commit: bool = True
    keep_index: bool = False


MUTATIONS: list[Mutation] = []


def mutation(
    rule: str, *, commit: bool = True, keep_index: bool = False
) -> Callable[[Callable[[Path], None]], Callable[[Path], None]]:
    def register(fn: Callable[[Path], None]) -> Callable[[Path], None]:
        MUTATIONS.append(Mutation(fn.__name__, rule, fn, commit, keep_index))
        return fn

    return register


def replace(vault: Path, rel: str, old: str, new: str) -> None:
    path = vault / rel
    text = path.read_text()
    assert text.count(old) == 1, f"{rel}: expected exactly one occurrence of {old!r}"
    path.write_text(text.replace(old, new))
