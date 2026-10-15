"""schema and missing-section: single-note checks shared with `labbrain validate`."""

from __future__ import annotations

from collections.abc import Iterator

from labbrain.findings import ERROR, WARNING, Finding
from labbrain.ids import is_valid_id
from labbrain.lint import LintContext, rule
from labbrain.notes import Note, future_agents_block, h2_headings
from labbrain.schema import FUTURE_AGENTS_HEADING, REQUIRED_SECTIONS
from labbrain.vault import Config

MAX_FUTURE_AGENTS_LINES = 3


def schema_findings(note: Note, config: Config) -> list[Finding]:
    out = [Finding(note.rel, note.error_line, "schema", ERROR, msg) for msg in note.errors]
    if note.data is None:
        return out
    raw_id = note.data.get("id")
    if isinstance(raw_id, str) and raw_id != note.stem:
        out.append(Finding(note.rel, 1, "schema", ERROR, "id does not match the filename"))
    note_type = note.type
    if note_type in REQUIRED_SECTIONS and not is_valid_id(note.stem, note_type, config.id_prefixes):
        out.append(Finding(note.rel, 1, "schema", ERROR, f"filename is not a valid {note_type} ID"))
    author = note.data.get("author")
    if isinstance(author, str) and not config.author_allowed(author):
        out.append(Finding(note.rel, 1, "schema", ERROR, "author is not in lab_members or agents"))
    return out


def section_findings(note: Note, config: Config) -> list[Finding]:
    if note.data is None or note.type not in REQUIRED_SECTIONS:
        return []
    out = []
    present = {title for _, title in h2_headings(note)}
    for section in REQUIRED_SECTIONS[note.type]:
        if section not in present:
            out.append(
                Finding(
                    note.rel,
                    note.body_line,
                    "missing-section",
                    WARNING,
                    f"missing required section: ## {section}",
                )
            )
    if config.is_agent(note.get_str("author")):
        block = future_agents_block(note)
        if block is None:
            message = f"agent-authored note must start with '## {FUTURE_AGENTS_HEADING}'"
        elif len(block) > MAX_FUTURE_AGENTS_LINES:
            message = (
                f"'## {FUTURE_AGENTS_HEADING}' block has more than {MAX_FUTURE_AGENTS_LINES} lines"
            )
        else:
            message = ""
        if message:
            out.append(Finding(note.rel, note.body_line, "missing-section", WARNING, message))
    return out


def check_note(note: Note, config: Config) -> list[Finding]:
    """All single-note checks: what `validate` runs on one file."""
    return schema_findings(note, config) + section_findings(note, config)


def _per_note(ctx: LintContext) -> list[Finding]:
    if "note_checks" not in ctx.cache:
        config = ctx.vault.config
        ctx.cache["note_checks"] = [
            f for note in ctx.vault.all_notes() for f in check_note(note, config)
        ]
    return ctx.cache["note_checks"]


@rule("schema", ERROR, "Frontmatter model, ID format, id = filename, author, duplicate IDs")
def schema_rule(ctx: LintContext) -> Iterator[Finding]:
    yield from (f for f in _per_note(ctx) if f.rule == "schema")
    for stem, group in ctx.vault.duplicates.items():
        for note in group:
            others = ", ".join(n.rel for n in group if n is not note)
            yield Finding(note.rel, 1, "schema", ERROR, f"duplicate ID {stem}; also at {others}")


@rule("missing-section", WARNING, "Required H2 sections; For-future-agents block on agent notes")
def missing_section_rule(ctx: LintContext) -> Iterator[Finding]:
    yield from (f for f in _per_note(ctx) if f.rule == "missing-section")
