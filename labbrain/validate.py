"""Single-file validation: what the M5 PostToolUse hook runs on every write.

Never loads the whole vault. It parses one note, checks it against the config,
and finds duplicate filenames with a directory walk.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from labbrain.findings import ERROR, INFO, Finding, sort_findings
from labbrain.layout import is_note_rel, iter_note_files
from labbrain.notes import parse_note
from labbrain.vault import Config, VaultNotFound, find_root, load_config

RULE = "validate"


def validate_path(path: Path, *, vault: Path | None = None) -> list[Finding]:
    target = path.expanduser().resolve()
    try:
        root = find_root(start=target.parent, explicit=vault)
    except VaultNotFound:
        return [Finding(target.name, 0, RULE, INFO, "not inside a vault; skipped")]
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        return [Finding(target.name, 0, RULE, INFO, "outside the vault; skipped")]
    if not target.is_file():
        return [Finding(rel, 0, RULE, ERROR, "file does not exist")]
    config = load_config(root)
    findings: list[Finding] = []
    if is_note_rel(rel):
        findings.extend(_check_note_file(target, root, config))
    return sort_findings(findings)


def _check_note_file(target: Path, root: Path, config: Config) -> list[Finding]:
    from labbrain.lint.rules.schema_rules import check_note

    note = parse_note(target, root)
    findings = check_note(note, config)
    for other in iter_note_files(root):
        if other.stem == target.stem and other.resolve() != target:
            where = other.relative_to(root).as_posix()
            findings.append(
                Finding(
                    note.rel, 1, "schema", ERROR, f"duplicate ID {target.stem}; also at {where}"
                )
            )
    return findings


def validate_paths(paths: Iterable[Path], *, vault: Path | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        findings.extend(validate_path(path, vault=vault))
    return sort_findings(findings)
