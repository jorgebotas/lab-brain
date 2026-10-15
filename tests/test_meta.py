"""The repository itself must contain no identifier-like text outside tests/.

docs/superpowers/ is excluded because its planning documents quote example
patterns on purpose; uv.lock is excluded because it is generated.
"""

from __future__ import annotations

from pathlib import Path

from labbrain.phi import ScanSettings, scan

REPO = Path(__file__).resolve().parents[1]
SKIP_TOP = {"tests", "docs", "uv.lock", "dist", "build", "__pycache__"}


def scan_targets() -> list[Path]:
    targets = [
        p for p in sorted(REPO.iterdir()) if not p.name.startswith(".") and p.name not in SKIP_TOP
    ]
    targets += [p for p in sorted((REPO / "docs").iterdir()) if p.name != "superpowers"]
    return targets


def test_repository_contains_no_identifier_like_text() -> None:
    findings = scan(scan_targets(), root=REPO, settings=ScanSettings(), allow=frozenset())
    assert findings == [], [f.to_dict() for f in findings]
