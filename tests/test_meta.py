"""Every tracked file outside tests/ and docs/superpowers/ must contain no identifier-like text.

tests/ generates synthetic identifiers on purpose, and docs/superpowers/ planning
documents quote example patterns on purpose. Targets come from `git ls-files`, so
untracked working-tree artifacts never change the result.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from labbrain.phi import ScanSettings, scan

REPO = Path(__file__).resolve().parents[1]
EXEMPT_PREFIXES = ("tests/", "docs/superpowers/")


def scan_targets() -> list[Path]:
    """Tracked files of this repository, minus the exempt directories."""
    if shutil.which("git") is None:
        pytest.skip("git is not available, so tracked files cannot be listed")
    proc = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        pytest.skip(f"git ls-files failed (not a git checkout?): {proc.stderr.strip()}")
    names = [name for name in proc.stdout.split("\0") if name]
    return [REPO / name for name in sorted(names) if not name.startswith(EXEMPT_PREFIXES)]


def test_repository_contains_no_identifier_like_text() -> None:
    targets = scan_targets()
    assert targets, "git ls-files listed no files to scan"
    findings = scan(targets, root=REPO, settings=ScanSettings(), allow=frozenset())
    assert findings == [], [f.to_dict() for f in findings]
