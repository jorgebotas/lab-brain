"""Hygiene rules: index-stale, concept-unsourced, inbox-age, dirty-code, undated-fact."""

from __future__ import annotations

from collections.abc import Iterator

from labbrain.findings import WARNING, Finding
from labbrain.index import is_stale
from labbrain.layout import INDEX_FILE
from labbrain.lint import LintContext, rule


@rule("index-stale", WARNING, "index.md differs from what `labbrain index` would generate")
def index_stale(ctx: LintContext) -> Iterator[Finding]:
    if is_stale(ctx.vault):
        message = "index.md is out of date; run `labbrain index`"
        yield Finding(INDEX_FILE, 0, "index-stale", WARNING, message)
