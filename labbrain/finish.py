"""`labbrain finish`: the end step of every writing skill.

Validate the written notes; only when they are clean, propagate supersession,
regenerate index.md and append to today's log. A skill therefore never leaves a
broken note listed in the index or the log.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from labbrain.errors import EngineError
from labbrain.findings import ERROR, Finding, sort_findings


class FinishError(EngineError):
    """finish was called with unusable input."""


@dataclass
class FinishResult:
    findings: list[Finding]
    index_updated: bool | None = None  # None when finish stopped after validation


def finish(
    paths: Sequence[Path],
    *,
    log_text: str,
    author: str | None,
    when: datetime,
    vault: Path | None = None,
) -> FinishResult:
    from labbrain import index, log, sync
    from labbrain.validate import validate_paths
    from labbrain.vault import Vault, find_root

    if not log.one_line(log_text):
        raise FinishError("--log text is empty")
    targets = [Path(p).expanduser().resolve() for p in paths]
    root = find_root(start=targets[0].parent, explicit=vault)
    if any(not target.is_relative_to(root) for target in targets):
        raise FinishError("a path is outside the vault")
    findings = validate_paths(targets, vault=root)
    if any(f.severity == ERROR for f in findings):
        return FinishResult(findings)
    loaded = Vault.load(root)
    changes, conflicts = sync.plan(loaded)
    written, failed = sync.apply(loaded, changes, when.date())
    findings = findings + sync.report(changes, conflicts, failed, verb="updated")
    if written:
        loaded = Vault.load(root)
    updated = index.write(loaded)
    log.append(root, log_text, when=when, author=author)
    return FinishResult(sort_findings(findings), updated)
