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


# --- schema -----------------------------------------------------------------


@mutation("schema")
def schema_bad_status(vault: Path) -> None:
    """Concept status outside its enum. Sections, sources and links are untouched."""
    replace(vault, CONCEPT, "status: active", "status: archived")


@mutation("schema")
def schema_id_mismatch(vault: Path) -> None:
    """`id` disagrees with the filename. Notes are keyed by filename, so links still resolve."""
    replace(vault, LITERATURE, "id: LIT-szegedy2016-rethinking", "id: LIT-szegedy2016-other")


@mutation("schema")
def schema_unknown_author(vault: Path) -> None:
    """Decision author outside lab_members and agents; a human author needs no agent block."""
    replace(vault, DECISION, "author: alice", "author: mallory")


@mutation("schema")
def schema_done_without_dataset(vault: Path) -> None:
    """Done experiment loses `dataset`. The dataset keeps two other inbound links."""
    replace(vault, BASELINE, "dataset: DS-20260801-main-split\n", "")


@mutation("schema")
def schema_invalid_yaml(vault: Path) -> None:
    """Literature frontmatter stops parsing. It has no ID-bearing fields, so no links
    are lost, and links to it still resolve by filename."""
    replace(vault, LITERATURE, "venue: CVPR", "venue: [CVPR")


@mutation("schema")
def schema_stray_file(vault: Path) -> None:
    """Markdown without frontmatter in a note folder. It has no type, so no other rule
    inspects it, and its text matches no PHI pattern."""
    (vault / "concepts" / "scratch-notes.md").write_text("just some text\n")


@mutation("schema")
def schema_duplicate_id(vault: Path) -> None:
    """Same idea filename in inbox and archive. Ideas are exempt from orphan and the
    copy is as recent as the original."""
    src = vault / IDEA_OPEN
    (vault / "ideas" / "archive" / src.name).write_text(src.read_text())


# --- missing-section ----------------------------------------------------------


@mutation("missing-section")
def missing_required_section(vault: Path) -> None:
    """EVAL-v1 loses its `## Known caveats` heading; the paragraph stays."""
    replace(vault, EVAL_V1, "## Known caveats\n\n", "")


@mutation("missing-section")
def missing_future_agents_block(vault: Path) -> None:
    """The agent-authored concept loses its leading block. undated-fact skips that
    block anyway, and the remaining lines are unchanged."""
    replace(
        vault,
        CONCEPT,
        "## For future agents\n\n"
        "Synthesis of what this project knows about label smoothing and calibration.\n"
        "Numbers here are copied from linked experiments; "
        "trust the experiment notes over this page.\n\n",
        "",
    )


# --- index-stale ---------------------------------------------------------------------


@mutation("index-stale", keep_index=True)
def index_stale_title(vault: Path) -> None:
    """The concept's title changes after the index was generated; titles are free text."""
    replace(
        vault,
        CONCEPT,
        'title: "Label smoothing and calibration"',
        'title: "Label smoothing, calibration and confidence"',
    )
