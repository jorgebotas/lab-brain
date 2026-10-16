"""Single-file validation: what the M5 PostToolUse hook runs on every write.

Never loads the whole vault. It parses one note, checks it against the config,
finds duplicate filenames with a directory walk, and scans the file for PHI when
the project is protected.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from labbrain.findings import ERROR, INFO, Finding, sort_findings
from labbrain.layout import is_note_rel, iter_note_files
from labbrain.notes import parse_note
from labbrain.vault import Config, find_root_or_none, load_config

RULE = "validate"


def validate_path(
    path: Path, *, vault: Path | None = None, configs: dict[Path, Config] | None = None
) -> list[Finding]:
    """Validate one file.

    Raises VaultNotFound when `vault` or LABBRAIN_VAULT names a directory without a
    config (a configuration problem, exit 2). Only auto-discovery failing is a skip.
    `configs` caches loaded configs by vault root; callers read it afterwards to see
    which vaults were touched (the CLI warns once per vault about engine_min_version).
    """
    target = path.expanduser().resolve()
    root = find_root_or_none(start=target.parent, explicit=vault)
    if root is None:
        return [Finding(target.name, 0, RULE, INFO, "not inside a vault; skipped")]
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        return [Finding(target.name, 0, RULE, INFO, "outside the vault; skipped")]
    if not target.is_file():
        return [Finding(rel, 0, RULE, ERROR, "file does not exist")]
    configs = {} if configs is None else configs
    if root not in configs:
        configs[root] = load_config(root)
    config = configs[root]
    findings: list[Finding] = []
    if is_note_rel(rel):
        findings.extend(_check_note_file(target, root, config))
    if config.protected_data:
        from labbrain.phi import ScanSettings, in_scan_scope, load_allowlist, scan

        if in_scan_scope(rel):
            findings.extend(
                scan(
                    [target],
                    root=root,
                    settings=ScanSettings.from_config(config, root),
                    allow=load_allowlist(root),
                    rule_name="phi",
                )
            )
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


def validate_paths(
    paths: Iterable[Path], *, vault: Path | None = None, configs: dict[Path, Config] | None = None
) -> list[Finding]:
    configs = {} if configs is None else configs
    findings: list[Finding] = []
    for path in paths:
        findings.extend(validate_path(path, vault=vault, configs=configs))
    return sort_findings(findings)
