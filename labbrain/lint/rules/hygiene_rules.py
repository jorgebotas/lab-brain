"""Hygiene rules: index-stale, concept-unsourced, inbox-age, dirty-code, undated-fact."""

from __future__ import annotations

import re
from collections.abc import Iterator

from labbrain.findings import WARNING, Finding
from labbrain.index import is_stale
from labbrain.layout import INDEX_FILE
from labbrain.lint import LintContext, rule
from labbrain.notes import H2_RE, body_lines
from labbrain.schema import FUTURE_AGENTS_HEADING

# Percentages, or decimals with at least two fractional digits.
METRIC_RE = re.compile(r"(?<![\w.])(?:\d+(?:\.\d+)?\s?%|\d*\.\d{2,})(?!\w|\.\w)")
_AS_OF_RE = re.compile(r"\bas of \d{4}-\d{2}-\d{2}\b", re.IGNORECASE)
_RUN_RE = re.compile(r"\brun_id\b|\brun:")
UNDATED_TYPES = frozenset({"concept", "claim"})
UNDATED_SKIP_SECTIONS = frozenset({"History", FUTURE_AGENTS_HEADING})


@rule("index-stale", WARNING, "index.md differs from what `labbrain index` would generate")
def index_stale(ctx: LintContext) -> Iterator[Finding]:
    if is_stale(ctx.vault):
        message = "index.md is out of date; run `labbrain index`"
        yield Finding(INDEX_FILE, 0, "index-stale", WARNING, message)


@rule("concept-unsourced", WARNING, "Concept with sources: []")
def concept_unsourced(ctx: LintContext) -> Iterator[Finding]:
    for note in ctx.vault.of_type("concept"):
        if note.data is not None and "sources" in note.data and not note.get_list("sources"):
            yield Finding(note.rel, 1, "concept-unsourced", WARNING, "concept cites no sources")


@rule("inbox-age", WARNING, "Open idea older than inbox_max_days")
def inbox_age(ctx: LintContext) -> Iterator[Finding]:
    limit = ctx.vault.config.inbox_max_days
    for note in ctx.vault.of_type("idea"):
        created = note.get_date("created")
        if note.get_str("status") == "open" and created and (ctx.today - created).days > limit:
            age = (ctx.today - created).days
            message = f"open for {age} days (limit {limit}); consolidate or drop it"
            yield Finding(note.rel, 1, "inbox-age", WARNING, message)


@rule("dirty-code", WARNING, "Experiment logged from a dirty code tree")
def dirty_code(ctx: LintContext) -> Iterator[Finding]:
    for note in ctx.vault.of_type("experiment"):
        code = note.get("code")
        if isinstance(code, dict) and code.get("dirty") is True:
            message = "logged from a dirty code tree; the SHA does not identify the code that ran"
            yield Finding(note.rel, 1, "dirty-code", WARNING, message)


def _stamp_re(prefixes: dict[str, str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(prefixes[t]) for t in ("experiment", "literature", "claim"))
    return re.compile(rf"\[\[(?:{alternatives})-")


@rule("undated-fact", WARNING, "Agent-written metric-like number without a run, link or date")
def undated_fact(ctx: LintContext) -> Iterator[Finding]:
    config = ctx.vault.config
    stamp = _stamp_re(config.id_prefixes)
    for note in ctx.vault.notes.values():
        if note.type not in UNDATED_TYPES or not config.is_agent(note.get_str("author")):
            continue
        section: str | None = None
        for lineno, line in body_lines(note):
            heading = H2_RE.match(line)
            if heading:
                section = heading.group(1)
                continue
            if section in UNDATED_SKIP_SECTIONS or line.lstrip().startswith("#"):
                continue
            if METRIC_RE.search(line) and not (
                stamp.search(line) or _RUN_RE.search(line) or _AS_OF_RE.search(line)
            ):
                message = "metric-like number without an EXP/LIT/CLM link, run id or 'as of' date"
                yield Finding(note.rel, lineno, "undated-fact", WARNING, message)
