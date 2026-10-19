"""Skeleton notes for `labbrain new`, generated from the schema registries.

Every skeleton passes `labbrain validate` with zero findings, so skills fill in
a valid note instead of writing frontmatter by hand, and IDs are always minted
by the tool.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labbrain.errors import EngineError
from labbrain.findings import strip_controls
from labbrain.ids import IdError, new_id, protocol_version
from labbrain.layout import TYPE_FOLDERS
from labbrain.notes import atomic_create, render_note
from labbrain.schema import DEFAULT_STATUS, FUTURE_AGENTS_HEADING, REQUIRED_SECTIONS
from labbrain.vault import Config

FUTURE_AGENTS_PLACEHOLDER = (
    "<!-- Up to three lines: what this note is, what is safe to rely on, what to check first. -->"
)

# Statuses `new --status` accepts beyond each type's default: only those whose skeleton
# validates (a done experiment needs a dataset, a superseded note a successor, ...).
NEW_STATUSES: dict[str, tuple[str, ...]] = {
    "experiment": ("planned", "running"),
    "decision": ("proposed", "accepted"),
}
CREATE_ATTEMPTS = 5


class ScaffoldError(EngineError):
    """A `new` option cannot be honoured."""


def allowed_statuses(note_type: str) -> tuple[str, ...]:
    return NEW_STATUSES.get(note_type, (DEFAULT_STATUS[note_type],))


def one_line(text: str) -> str:
    """`text` on one line: control characters and line breaks become single spaces."""
    return " ".join(strip_controls(text).split())


# Type-specific fields in display order. A list default renders as a flow list (`[]`).
TYPE_FIELDS: dict[str, dict[str, Any]] = {
    "experiment": {
        "hypothesis": None,
        "protocol": None,
        "tracker": None,
        "code": None,
        "config_hash": None,
        "dataset": None,
        "metrics": [],
        "supersedes": None,
        "superseded_by": None,
    },
    "protocol": {"version": None, "changes_from": None, "comparable_with": []},
    "claim": {
        "statement": None,
        "value": None,
        "value_format": None,
        "tolerance": None,
        "evidence": [],
        "protocol": None,
        "manuscript_locations": [],
    },
    "idea": {"consolidated_into": None},
    "concept": {"sources": []},
    "decision": {"supersedes": None, "superseded_by": None},
    "literature": {
        "doi": None,
        "arxiv": None,
        "url": None,
        "year": None,
        "venue": None,
        "relevance": None,
    },
    "handoff": {"agent": None, "session_goal": None, "files_touched": []},
    "dataset": {
        "location": None,
        "extracted": None,
        "split_of": None,
        "counts": None,
        "protected": None,
        "supersedes": None,
        "superseded_by": None,
    },
}


def _flow(items: Iterable[Any]) -> CommentedSeq:
    seq = CommentedSeq(list(items))
    seq.fa.set_flow_style()
    return seq


def skeleton(
    note_type: str,
    *,
    note_id: str,
    title: str,
    author: str,
    now: datetime,
    config: Config,
    links: Iterable[str] = (),
    extra: Mapping[str, Any] | None = None,
    summary: str = "",
    body: str = "",
    tags: Iterable[str] = (),
    status: str | None = None,
) -> str:
    data = CommentedMap()
    data["id"] = note_id
    data["type"] = note_type
    data["title"] = title
    data["created"] = now.date()
    data["updated"] = now.date()
    data["author"] = author
    data["status"] = status or DEFAULT_STATUS[note_type]
    data["tags"] = _flow(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
    data["links"] = _flow(links)
    for key, default in TYPE_FIELDS[note_type].items():
        data[key] = _flow(default) if isinstance(default, list) else default
    for key, value in (extra or {}).items():
        data[key] = value
    sections = []
    if config.is_agent(author):
        line = one_line(summary) or FUTURE_AGENTS_PLACEHOLDER
        sections.append(f"## {FUTURE_AGENTS_HEADING}\n\n{line}\n")
    if body.strip():
        sections.append(body.strip("\n") + "\n")
    sections += [f"## {section}\n" for section in REQUIRED_SECTIONS[note_type]]
    return render_note(data, "\n".join(sections))


def create(
    root: Path,
    config: Config,
    note_type: str,
    *,
    title: str,
    author: str,
    now: datetime,
    links: Iterable[str] = (),
    agent: str = "",
    first_author: str = "",
    year: int | None = None,
    name: str = "",
    summary: str = "",
    body: str = "",
    tags: Iterable[str] = (),
    status: str | None = None,
) -> Path:
    if status is not None and status not in allowed_statuses(note_type):
        choices = ", ".join(allowed_statuses(note_type))
        raise ScaffoldError(f"--status for a new {note_type} must be one of: {choices}")
    if any(line.startswith("## ") for line in body.splitlines()):
        raise ScaffoldError("--body must not contain level-2 headings")
    agent = agent or author
    links, tags = list(links), list(tags)
    for _ in range(CREATE_ATTEMPTS):
        note_id = new_id(
            note_type,
            root=root,
            now=now,
            title=title,
            prefixes=config.id_prefixes,
            agent=agent,
            first_author=first_author,
            year=year,
            name=name,
        )
        extra: dict[str, Any] = {}
        if note_type == "protocol":
            extra["version"] = protocol_version(note_id, config.id_prefixes)
        elif note_type == "handoff":
            extra["agent"] = agent
        elif note_type == "literature":
            extra["year"] = year
        path = root / TYPE_FOLDERS[note_type] / f"{note_id}.md"
        text = skeleton(
            note_type,
            note_id=note_id,
            title=title,
            author=author,
            now=now,
            config=config,
            links=links,
            extra=extra,
            summary=summary,
            body=body,
            tags=tags,
            status=status,
        )
        try:
            atomic_create(path, text)
        except FileExistsError:
            continue  # another writer took this ID; new_id sees the file next time
        return path
    raise IdError(f"could not create a {note_type} note: every candidate ID was taken")
