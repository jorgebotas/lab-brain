"""Fixtures for the smoke tests: skip without claude or credentials; a committed vault."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from harness import LOGIN
from helpers import commit_all, copy_fixture, copy_runs, git


@pytest.fixture
def claude_bin() -> str:
    path = shutil.which("claude")
    if path is None or not os.access(path, os.X_OK):
        pytest.skip("claude is not installed")
    if not (os.environ.get("ANTHROPIC_API_KEY") or LOGIN):
        pytest.skip("set ANTHROPIC_API_KEY, or LABBRAIN_SMOKE_LOGIN=1 to use your login")
    return path


@pytest.fixture
def smoke_vault(tmp_path: Path) -> Path:
    vault = copy_fixture(tmp_path / "vault")
    copy_runs(vault)
    git(vault, "init", "-q", "-b", "main")
    commit_all(vault, "smoke vault")
    return vault
