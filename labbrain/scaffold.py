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
from labbrain.notes import H2_RE, HEADING_RE, atomic_create, render_note
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
# Code fence markers, as the body scanner (notes.iter_body_lines) toggles on them.
FENCES = ("```", "~~~")
# `--body` goes under its own heading, so it never counts as For-future-agents lines.
BODY_HEADING = "Notes"


class ScaffoldError(EngineError):
    """A `new` option cannot be honoured."""


def allowed_statuses(note_type: str) -> tuple[str, ...]:
    return NEW_STATUSES.get(note_type, (DEFAULT_STATUS[note_type],))


def one_line(text: str) -> str:
    """`text` on one line: control characters and line breaks become single spaces."""
    return " ".join(strip_controls(text).split())


def _body_lines(body: str) -> list[str]:
    """`body` split into lines, each with control characters replaced by spaces."""
    return [strip_controls(line) for line in body.splitlines()]


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
    section_text: Mapping[str, str] | None = None,
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
    text = "\n".join(_body_lines(body)).strip("\n")
    if text.strip():
        sections.append(f"## {BODY_HEADING}\n\n{text}\n")
    for section in REQUIRED_SECTIONS[note_type]:
        text = (section_text or {}).get(section, "").strip("\n")
        sections.append(f"## {section}\n\n{text}\n" if text else f"## {section}\n")
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
    extra: Mapping[str, Any] | None = None,
    section_text: Mapping[str, str] | None = None,
) -> Path:
    if status is not None and status not in allowed_statuses(note_type):
        choices = ", ".join(allowed_statuses(note_type))
        raise ScaffoldError(f"--status for a new {note_type} must be one of: {choices}")
    if any(H2_RE.match(line) for line in _body_lines(body)):
        raise ScaffoldError("--body must not contain level-2 headings")
    if HEADING_RE.match(one_line(summary)):
        raise ScaffoldError("--summary must not be a heading")
    if one_line(summary).startswith(FENCES):
        raise ScaffoldError("--summary must not start a code fence")
    if sum(1 for line in _body_lines(body) if line.lstrip().startswith(FENCES)) % 2:
        raise ScaffoldError("--body has an unclosed code fence")
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
        fields: dict[str, Any] = {}
        if note_type == "protocol":
            fields["version"] = protocol_version(note_id, config.id_prefixes)
        elif note_type == "handoff":
            fields["agent"] = agent
        elif note_type == "literature":
            fields["year"] = year
        fields.update(extra or {})
        path = root / TYPE_FOLDERS[note_type] / f"{note_id}.md"
        text = skeleton(
            note_type,
            note_id=note_id,
            title=title,
            author=author,
            now=now,
            config=config,
            links=links,
            extra=fields,
            summary=summary,
            body=body,
            tags=tags,
            status=status,
            section_text=section_text,
        )
        try:
            atomic_create(path, text)
        except FileExistsError:
            continue  # another writer took this ID; new_id sees the file next time
        return path
    raise IdError(f"could not create a {note_type} note: every candidate ID was taken")
