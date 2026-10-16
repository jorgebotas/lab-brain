from __future__ import annotations

import os
from pathlib import Path

import pytest
from helpers import PINNED_NOW, commit_all, copy_fixture, git

INHERITED_GIT_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES",
)


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep fixture repos independent of an outer repo (hooks, rebase --exec) and user config."""
    for name in INHERITED_GIT_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A committed git copy of the valid fixture, with time and vault pinned."""
    dest = copy_fixture(tmp_path / "vault")
    git(dest, "init", "-q", "-b", "main")
    commit_all(dest, "valid fixture")
    monkeypatch.setenv("LABBRAIN_NOW", PINNED_NOW)
    monkeypatch.setenv("LABBRAIN_VAULT", str(dest))
    return dest
