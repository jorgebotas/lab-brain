"""Fixtures for the smoke tests: skip without claude or credentials; a committed vault."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import NoReturn

import pytest
from harness import LOGIN
from helpers import commit_all, copy_fixture, copy_runs, git

REQUIRED = os.environ.get("LABBRAIN_SMOKE_REQUIRED") == "1"


def skip_or_fail(reason: str) -> NoReturn:
    """Skip, unless LABBRAIN_SMOKE_REQUIRED=1 says a skip would hide a broken setup."""
    if REQUIRED:
        pytest.fail(f"LABBRAIN_SMOKE_REQUIRED=1 but {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture
def claude_bin() -> str:
    path = shutil.which("claude")
    if path is None or not os.access(path, os.X_OK):
        skip_or_fail("claude is not installed")
    if not (os.environ.get("ANTHROPIC_API_KEY") or LOGIN):
        skip_or_fail("set ANTHROPIC_API_KEY, or LABBRAIN_SMOKE_LOGIN=1 to use your login")
    return path


@pytest.fixture
def smoke_vault(tmp_path: Path) -> Path:
    vault = copy_fixture(tmp_path / "vault")
    copy_runs(vault)
    git(vault, "init", "-q", "-b", "main")
    commit_all(vault, "smoke vault")
    return vault
