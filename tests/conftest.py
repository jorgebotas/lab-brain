from __future__ import annotations

from pathlib import Path

import pytest
from helpers import PINNED_NOW, commit_all, copy_fixture, git


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A committed git copy of the valid fixture, with time and vault pinned."""
    dest = copy_fixture(tmp_path / "vault")
    git(dest, "init", "-q", "-b", "main")
    commit_all(dest, "valid fixture")
    monkeypatch.setenv("LABBRAIN_NOW", PINNED_NOW)
    monkeypatch.setenv("LABBRAIN_VAULT", str(dest))
    return dest
