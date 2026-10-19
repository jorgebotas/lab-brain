"""Derived state the tool maintains: supersession links and protocol freezing.

Idempotent. It only performs transitions that frozen-edit allows and writes only
the fields it changes (plus `updated`), keeping every other line as it was, so its
output never trips frozen-edit. Conflict messages print an existing superseded_by
value only through findings.display_id.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from labbrain.findings import ERROR, INFO, Finding, display_id, sort_findings
from labbrain.notes import update_frontmatter
from labbrain.schema import MODELS
from labbrain.vault import Vault


def _supersedable(note_type: str | None) -> bool:
    """Only types whose schema has a superseded_by field (and so a superseded status)."""
    model = MODELS.get(note_type) if note_type is not None else None
    return model is not None and "superseded_by" in model.model_fields


def _with_article(word: str) -> str:
    return f"{'an' if word[:1] in 'aeiou' else 'a'} {word}"


@dataclass(frozen=True)
class Change:
    note_id: str
    rel: str
    updates: dict[str, Any]
    reason: str


@dataclass(frozen=True)
class Conflict:
    note_id: str
    rel: str
    message: str


def plan(vault: Vault) -> tuple[list[Change], list[Conflict]]:
    changes: list[Change] = []
    conflicts: list[Conflict] = []

    successors: dict[str, list[str]] = defaultdict(list)
    for note in vault.notes.values():
        target = note.get_str("supersedes")
        if target:
            successors[target].append(note.stem)
    for old_id in sorted(successors):
        old = vault.get(old_id)
        if old is None:
            continue  # broken-link reports it
        if old_id in successors[old_id]:
            message = f"{old_id} claims to supersede itself"
            conflicts.append(Conflict(old_id, old.rel, message))
            continue
        if not _supersedable(old.type):
            kind = _with_article(old.type) if old.type in MODELS else "of no known type"
            message = f"{old_id} is {kind} and cannot be superseded"
            conflicts.append(Conflict(old_id, old.rel, message))
            continue
        news = sorted(successors[old_id])
        if len(news) > 1:
            message = f"{old_id} is superseded by more than one note: {', '.join(news)}"
            conflicts.append(Conflict(old_id, old.rel, message))
            continue
        new = news[0]
        current = old.get_str("superseded_by")
        if current and current != new:
            message = (
                f"{old_id} is already superseded by {display_id(current, vault.notes, vault.config.id_prefixes)}; "
                f"{new} also claims to supersede it"
            )
            conflicts.append(Conflict(old_id, old.rel, message))
            continue
        updates: dict[str, Any] = {}
        if old.get_str("status") != "superseded":
            updates["status"] = "superseded"
        if current != new:
            updates["superseded_by"] = new
        if updates:
            changes.append(Change(old_id, old.rel, updates, f"superseded by {new}"))

    done_protocols = {
        exp.get_str("protocol")
        for exp in vault.of_type("experiment")
        if exp.get_str("status") == "done"
    }
    for protocol_id in sorted(p for p in done_protocols if p):
        protocol = vault.get(protocol_id)
        if (
            protocol is not None
            and protocol.type == "protocol"
            and protocol.get_str("status") == "draft"
        ):
            changes.append(
                Change(
                    protocol_id,
                    protocol.rel,
                    {"status": "frozen"},
                    "referenced by a done experiment",
                )
            )
    return changes, conflicts


def apply(vault: Vault, changes: list[Change], today: date) -> tuple[list[str], list[Conflict]]:
    """Write each change; returns (paths written, changes that could not be written).

    A failed write never stops the run: the remaining changes are still applied.
    """
    written: list[str] = []
    failed: list[Conflict] = []
    for change in changes:
        try:
            changed = update_frontmatter(
                vault.root / change.rel, {**change.updates, "updated": today}
            )
        except ValueError as exc:  # names only the file and a line
            failed.append(Conflict(change.note_id, change.rel, f"could not write: {exc}"))
            continue
        except OSError:
            message = "could not write: file could not be written"
            failed.append(Conflict(change.note_id, change.rel, message))
            continue
        if changed:
            written.append(change.rel)
    return written, failed


def report(
    changes: list[Change], conflicts: list[Conflict], failed: list[Conflict], *, verb: str
) -> list[Finding]:
    """Sync results as findings: conflicts and failed writes are errors, changes are info."""
    findings = [Finding(c.rel, 1, "sync", ERROR, c.message) for c in conflicts + failed]
    failed_rels = {c.rel for c in failed}
    for change in changes:
        if change.rel in failed_rels:
            continue
        fields = ", ".join(f"{key} → {value}" for key, value in change.updates.items())
        findings.append(Finding(change.rel, 1, "sync", INFO, f"{verb}: {fields} ({change.reason})"))
    return sort_findings(findings)
