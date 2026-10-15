"""broken-link and orphan."""

from __future__ import annotations

from collections.abc import Iterator

from labbrain.findings import ERROR, WARNING, Finding, display_id
from labbrain.lint import LintContext, rule

ORPHAN_EXEMPT = frozenset({"idea", "handoff"})


def _vault_filenames(ctx: LintContext) -> set[str]:
    if "filenames" not in ctx.cache:
        root = ctx.vault.root
        ctx.cache["filenames"] = {
            p.name
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts
        }
    return ctx.cache["filenames"]


def _path_exists(ctx: LintContext, target: str) -> bool:
    if "/" in target:
        return (ctx.vault.root / target).exists()
    return target in _vault_filenames(ctx)  # Obsidian resolves bare filenames anywhere


@rule("broken-link", ERROR, "Every wikilink and ID-bearing frontmatter value resolves")
def broken_link(ctx: LintContext) -> Iterator[Finding]:
    for note in ctx.vault.all_notes():
        for ref in note.refs:
            # Only body wikilinks may name files; every frontmatter value must be a note ID.
            if ref.field == "body" and ref.is_path:
                if not _path_exists(ctx, ref.target):
                    message = f"{ref.field}: missing file {display_id(ref.target)}"
                    yield Finding(note.rel, ref.line, "broken-link", ERROR, message)
            elif ref.target not in ctx.vault.notes:
                message = f"{ref.field}: unresolved link [[{display_id(ref.target)}]]"
                yield Finding(note.rel, ref.line, "broken-link", ERROR, message)


@rule("orphan", WARNING, "Note with no inbound links (ideas and handoffs exempt)")
def orphan(ctx: LintContext) -> Iterator[Finding]:
    for stem, note in ctx.vault.notes.items():
        if note.type is None or note.type in ORPHAN_EXEMPT:
            continue
        if not ctx.vault.inbound.get(stem):
            yield Finding(note.rel, 1, "orphan", WARNING, "no inbound links")
