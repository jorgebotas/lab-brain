"""protocol-missing, cross-protocol, claim-stale and duplicate-config.

These rules read raw frontmatter (Note.get_*), never the pydantic model, so a
note with one bad field is still checked for everything else.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from labbrain.findings import ERROR, WARNING, Finding
from labbrain.lint import LintContext, rule
from labbrain.notes import Note
from labbrain.vault import Vault

STALE_EVIDENCE = frozenset({"superseded", "failed"})


def comparable(a: str, b: str, vault: Vault) -> bool:
    """Reflexive and symmetric, not transitive. Older protocols are frozen and cannot
    list newer ones, so either side may declare comparability."""
    if a == b:
        return True
    pa, pb = vault.get(a), vault.get(b)
    return (pa is not None and b in pa.get_list("comparable_with")) or (
        pb is not None and a in pb.get_list("comparable_with")
    )


@rule("protocol-missing", ERROR, "Experiment with status done and no protocol")
def protocol_missing(ctx: LintContext) -> Iterator[Finding]:
    for exp in ctx.vault.of_type("experiment"):
        if exp.get_str("status") == "done" and not exp.get_str("protocol"):
            yield Finding(exp.rel, 1, "protocol-missing", ERROR, "done experiment has no protocol")


@rule("cross-protocol", ERROR, "Claim evidence uses a protocol not comparable with the claim's")
def cross_protocol(ctx: LintContext) -> Iterator[Finding]:
    for claim in ctx.vault.of_type("claim"):
        claim_protocol = claim.get_str("protocol")
        if not claim_protocol or ctx.vault.get(claim_protocol) is None:
            continue  # broken-link reports an unresolved protocol
        for evidence_id in claim.get_list("evidence"):
            exp = ctx.vault.get(evidence_id)
            if exp is None or exp.type != "experiment":
                continue
            exp_protocol = exp.get_str("protocol")
            if not exp_protocol or ctx.vault.get(exp_protocol) is None:
                continue  # broken-link reports an unresolved protocol
            if not comparable(claim_protocol, exp_protocol, ctx.vault):
                message = (
                    f"evidence {evidence_id} uses {exp_protocol}, "
                    f"not comparable with the claim's {claim_protocol}"
                )
                yield Finding(claim.rel, 1, "cross-protocol", ERROR, message)


@rule("claim-stale", WARNING, "Claim evidence is superseded or failed")
def claim_stale(ctx: LintContext) -> Iterator[Finding]:
    for claim in ctx.vault.of_type("claim"):
        for evidence_id in claim.get_list("evidence"):
            exp = ctx.vault.get(evidence_id)
            status = exp.get_str("status") if exp is not None else None
            if exp is not None and exp.type == "experiment" and status in STALE_EVIDENCE:
                yield Finding(
                    claim.rel, 1, "claim-stale", WARNING, f"evidence {evidence_id} is {status}"
                )


def _supersession_pair(a: Note, b: Note) -> bool:
    return a.get_str("supersedes") == b.stem or b.get_str("supersedes") == a.stem


@rule("duplicate-config", WARNING, "Two live experiments share config_hash and protocol")
def duplicate_config(ctx: LintContext) -> Iterator[Finding]:
    groups: dict[tuple[str, str], list[Note]] = defaultdict(list)
    for exp in ctx.vault.of_type("experiment"):
        config_hash, protocol = exp.get_str("config_hash"), exp.get_str("protocol")
        if config_hash and protocol and exp.get_str("status") != "superseded":
            groups[(config_hash, protocol)].append(exp)
    for group in groups.values():
        for exp in group:
            others = sorted(
                o.stem for o in group if o is not exp and not _supersession_pair(exp, o)
            )
            if others:
                message = f"same config_hash and protocol as {', '.join(others)}"
                yield Finding(exp.rel, 1, "duplicate-config", WARNING, message)
