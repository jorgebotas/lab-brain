"""Read-only graph queries for skills and non-Claude agents (`list`, `links`)."""

from __future__ import annotations

from typing import Any

from labbrain.findings import display_id
from labbrain.vault import Vault


def list_notes(
    vault: Vault,
    *,
    note_type: str | None = None,
    status: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for stem in sorted(vault.notes):
        note = vault.notes[stem]
        if note_type and note.type != note_type:
            continue
        if status and note.get_str("status") != status:
            continue
        if tag and tag not in note.get_list("tags"):
            continue
        created = note.get_date("created")
        rows.append(
            {
                "id": stem,
                "type": note.type,
                "status": note.get_str("status"),
                "title": note.get_str("title"),
                "created": created.isoformat() if created else None,
                "path": note.rel,
            }
        )
    return rows


def links(vault: Vault, note_id: str) -> dict[str, Any]:
    if note_id not in vault.notes:
        raise KeyError(note_id)
    return {
        "id": note_id,
        "in": sorted({display_id(t, vault.notes) for t in vault.inbound.get(note_id, ())}),
        "out": sorted({display_id(t, vault.notes) for t in vault.outbound.get(note_id, ())}),
    }
