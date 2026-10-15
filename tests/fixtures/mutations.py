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


# --- broken-link / orphan ------------------------------------------------------

ORPHAN_LITERATURE = """---
id: LIT-doe2020-calibration
type: literature
title: "A study of calibration"
created: 2026-10-02
updated: 2026-10-02
author: bob
status: active
tags: []
links: []
year: 2020
relevance: low
---
## Summary

A survey of calibration metrics.

## Methods worth borrowing

Reliability diagrams.

## Results to compare against

None under our protocols.

## Style notes

Clear figures.
"""


@mutation("broken-link")
def broken_body_link(vault: Path) -> None:
    """Concept links to an ID that does not exist; the line carries no number."""
    replace(
        vault,
        CONCEPT,
        "[[ADR-20260905-adopt-eval-v2]] · [[LIT-szegedy2016-rethinking]]",
        "[[ADR-20260905-adopt-eval-v2]] · [[LIT-szegedy2016-rethinking]] · [[EXP-20990101-nowhere]]",
    )


@mutation("broken-link")
def broken_frontmatter_link(vault: Path) -> None:
    """Decision `links` names a missing protocol; EVAL-v2 keeps its other inbound links."""
    replace(vault, DECISION, "links: [EVAL-v2]", "links: [EVAL-v2, EVAL-v9]")


@mutation("broken-link")
def broken_embed(vault: Path) -> None:
    """Experiment embeds a figure that does not exist; path targets never touch the ID graph."""
    replace(vault, BASELINE, "## Next\n", "## Next\n\n![[figures/roc.png]]\n")


@mutation("orphan")
def orphan_new_literature(vault: Path) -> None:
    """A complete, valid literature note that nothing links to."""
    (vault / "literature" / "LIT-doe2020-calibration.md").write_text(ORPHAN_LITERATURE)


# --- protocol and claim rules ------------------------------------------------------


@mutation("protocol-missing")
def protocol_missing(vault: Path) -> None:
    """Done experiment loses `protocol`; EVAL-v2 keeps inbound links from the baseline,
    the claim and the decision, and the claim's evidence is the baseline."""
    replace(vault, SMOOTHING, "protocol: EVAL-v2\n", "")


@mutation("cross-protocol")
def cross_protocol(vault: Path) -> None:
    """Claim moves to EVAL-v1, which nothing declares comparable with EVAL-v2."""
    replace(vault, CLAIM, "protocol: EVAL-v2", "protocol: EVAL-v1")


@mutation("claim-stale")
def claim_stale_failed_evidence(vault: Path) -> None:
    """The claim's evidence experiment is now `failed`. EVAL-v2 is still referenced by the
    other done experiment, so sync has nothing to do."""
    replace(vault, BASELINE, "status: done", "status: failed")


@mutation("duplicate-config")
def duplicate_config(vault: Path) -> None:
    """Both done experiments share a config hash and protocol and neither supersedes."""
    replace(
        vault,
        SMOOTHING,
        'config_hash: "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"',
        'config_hash: "sha256:3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b"',
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


# --- hygiene -------------------------------------------------------------------------


@mutation("concept-unsourced")
def concept_unsourced(vault: Path) -> None:
    """Concept sources emptied. label-smoothing keeps inbound links from the concept body
    and the handoff; the paper keeps the concept body and the decision."""
    replace(
        vault,
        CONCEPT,
        "sources: [EXP-20260910-label-smoothing, LIT-szegedy2016-rethinking]",
        "sources: []",
    )


@mutation("inbox-age")
def inbox_age(vault: Path) -> None:
    """The open idea was created more than 30 days before the pinned date."""
    replace(vault, IDEA_OPEN, "created: 2026-10-10", "created: 2026-08-01")


@mutation("dirty-code")
def dirty_code(vault: Path) -> None:
    """The baseline was logged from a dirty tree."""
    replace(vault, BASELINE, "dirty: false", "dirty: true")


@mutation("undated-fact")
def undated_fact(vault: Path) -> None:
    """An agent-written concept quotes a number with no stamp; no PHI pattern matches."""
    replace(
        vault,
        CONCEPT,
        "which tends to improve calibration.\n",
        "which tends to improve calibration.\n\nIn our runs calibration error dropped to 0.04.\n",
    )


# --- sync-pending ------------------------------------------------------------------


@mutation("sync-pending")
def sync_pending_supersession(vault: Path) -> None:
    """label-smoothing now supersedes the baseline but sync has not run: the baseline is
    still `done`, so claim-stale stays quiet, and the two config hashes differ."""
    replace(
        vault,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )


@mutation("sync-pending")
def sync_pending_protocol(vault: Path) -> None:
    """EVAL-v2 is `draft` although done experiments reference it (committed, so no
    frozen-edit)."""
    replace(vault, EVAL_V2, "status: frozen", "status: draft")


# --- frozen-edit (left uncommitted) --------------------------------------------------


@mutation("frozen-edit", commit=False)
def frozen_body_rewrite(vault: Path) -> None:
    """A done experiment's Results row is rewritten. Experiments are exempt from
    undated-fact and the frontmatter metrics are untouched."""
    replace(
        vault, BASELINE, "| auroc_median | 0.81 | run-001 |", "| auroc_median | 0.83 | run-001 |"
    )


@mutation("frozen-edit", commit=False)
def frozen_status_laundering(vault: Path) -> None:
    """done → running on a frozen experiment. EVAL-v2 is still referenced by the other done
    experiment, and running evidence is not stale."""
    replace(vault, BASELINE, "status: done", "status: running")


@mutation("frozen-edit", commit=False)
def frozen_field_change(vault: Path) -> None:
    """A frozen experiment's hypothesis is rewritten."""
    replace(
        vault,
        SMOOTHING,
        'hypothesis: "Label smoothing improves calibration without lowering AUROC"',
        'hypothesis: "Label smoothing improves AUROC"',
    )


@mutation("frozen-edit", commit=False)
def frozen_handoff_deleted(vault: Path) -> None:
    """Handoffs are always frozen. Every note the handoff links to keeps another inbound link."""
    (vault / HANDOFF).unlink()


@mutation("frozen-edit", commit=False)
def frozen_raw_modified(vault: Path) -> None:
    """raw/ files are immutable."""
    with (vault / RAW_PAPER).open("a") as handle:
        handle.write("An added line.\n")


@mutation("frozen-edit", commit=False)
def frozen_idea_body_rewrite(vault: Path) -> None:
    """Ideas are create-only; rewording one is a modification."""
    replace(vault, IDEA_OPEN, "see whether late-epoch calibration holds.", "see whether it helps.")


@mutation("frozen-edit", commit=False)
def frozen_decision_retitled(vault: Path) -> None:
    """An accepted ADR's title changes."""
    replace(
        vault,
        DECISION,
        'title: "Adopt EVAL-v2 for all new experiments"',
        'title: "Adopt EVAL-v2"',
    )
