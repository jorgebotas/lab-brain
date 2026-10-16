"""pre-commit can install and run both hooks from this repository."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.network
@pytest.mark.skipif(shutil.which("pre-commit") is None, reason="pre-commit is not installed")
@pytest.mark.parametrize("hook", ["labbrain-lint", "labbrain-phi-scan"])
def test_hook_runs_clean_on_the_valid_fixture(vault_dir: Path, hook: str) -> None:
    proc = subprocess.run(
        ["pre-commit", "try-repo", str(REPO), hook, "--all-files"],
        cwd=vault_dir,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
