from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fixtures.mutations import CONCEPT, IDEA_OPEN, replace

from labbrain.layout import is_note_rel
from labbrain.validate import validate_path, validate_paths
from labbrain.vault import ENV_VAULT, VaultNotFound


def note_paths(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.md") if is_note_rel(p.relative_to(root).as_posix())]


def test_fixture_notes_validate_clean(vault_dir: Path) -> None:
    assert validate_paths(note_paths(vault_dir)) == []


def test_non_note_files_get_no_schema_check(vault_dir: Path) -> None:
    paths = [vault_dir / "experiments" / "README.md", vault_dir / "log" / "2026-10-14.md"]
    assert validate_paths(paths) == []


def test_outside_vault_is_info(vault_dir: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.md"
    other.write_text("x\n")
    assert [(f.rule, f.severity) for f in validate_path(other)] == [("validate", "info")]


def test_missing_file_is_an_error(vault_dir: Path) -> None:
    findings = validate_path(vault_dir / "experiments" / "EXP-20990101-none.md")
    assert [(f.rule, f.severity) for f in findings] == [("validate", "error")]


def test_duplicate_detected_without_loading_vault(vault_dir: Path) -> None:
    src = vault_dir / IDEA_OPEN
    shutil.copy(src, vault_dir / "ideas" / "archive" / src.name)
    findings = validate_path(src)
    assert [(f.rule, f.message.split(";")[0]) for f in findings] == [
        ("schema", "duplicate ID IDEA-20261010-smoothing-schedule")
    ]


def test_broken_note_reports_schema_error(vault_dir: Path) -> None:
    replace(vault_dir, CONCEPT, "status: active", "status: archived")
    findings = validate_path(vault_dir / CONCEPT)
    assert [(f.rule, f.severity) for f in findings] == [("schema", "error")]


def test_explicit_vault_without_config_raises(vault_dir: Path, tmp_path: Path) -> None:
    bogus = tmp_path / "no-config"
    bogus.mkdir()
    with pytest.raises(VaultNotFound):
        validate_path(vault_dir / CONCEPT, vault=bogus)


def test_env_vault_without_config_raises(
    vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bogus = tmp_path / "no-config"
    bogus.mkdir()
    monkeypatch.setenv(ENV_VAULT, str(bogus))
    with pytest.raises(VaultNotFound):
        validate_path(vault_dir / CONCEPT)


def test_discovery_without_vault_is_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAULT, raising=False)
    other = tmp_path / "loose" / "elsewhere.md"
    other.parent.mkdir()
    other.write_text("x\n")
    findings = validate_path(other)
    assert [(f.rule, f.severity, f.message) for f in findings] == [
        ("validate", "info", "not inside a vault; skipped")
    ]
