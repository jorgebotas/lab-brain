"""Derived state the tool maintains: supersession links and protocol freezing.

Idempotent, and it only performs transitions that frozen-edit allows, so its
output never trips frozen-edit.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from labbrain.notes import update_frontmatter
from labbrain.vault import Vault

_ID_SHAPED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$")


def _shown_id(vault: Vault, value: str) -> str:
    """A field value is printed only if it names a note or at least looks like an ID."""
    if vault.get(value) is not None or _ID_SHAPED.match(value):
        return value
    return "<not a valid note ID>"


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
        news = sorted(successors[old_id])
        if len(news) > 1:
            message = f"{old_id} is superseded by more than one note: {', '.join(news)}"
            conflicts.append(Conflict(old_id, old.rel, message))
            continue
        new = news[0]
        current = old.get_str("superseded_by")
        if current and current != new:
            message = (
                f"{old_id} is already superseded by {_shown_id(vault, current)}; "
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


def apply(vault: Vault, changes: list[Change], today: date) -> list[str]:
    written = []
    for change in changes:
        if update_frontmatter(vault.root / change.rel, {**change.updates, "updated": today}):
            written.append(change.rel)
    return written
