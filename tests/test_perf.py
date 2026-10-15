"""Budgets from the spec: lint < 3 s on 3,000 notes; validate < 300 ms per file."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, TODAY, commit_all, git, make_vault, write

from labbrain import lint
from labbrain.findings import ERROR, Finding
from labbrain.vault import Vault

PROTOCOL = """---
id: EVAL-v1
type: protocol
title: "Bulk protocol"
created: 2026-08-01
updated: 2026-08-01
author: alice
status: frozen
tags: []
links: []
version: 1
comparable_with: []
---
## Definition

AUROC on the test split.

## Changes from previous version

First version.

## Known caveats

None.
"""

DATASET = """---
id: DS-20260801-bulk
type: dataset
title: "Bulk dataset"
created: 2026-08-01
updated: 2026-08-01
author: alice
status: active
tags: []
links: [EVAL-v1]
location: "s3://bulk/"
---
## Source

Synthetic.

## Inclusion and exclusion

All rows.

## Split definition

Fixed split.

## Known issues

None.
"""

EXPERIMENT = """---
id: EXP-20260901-run-{i}
type: experiment
title: "Run {i}"
created: 2026-09-01
updated: 2026-09-01
author: alice
status: done
tags: [bulk]
links: []
protocol: EVAL-v1
dataset: DS-20260801-bulk
config_hash: "sha256:bulk-{i}"
metrics:
  - {{name: auroc, value: 0.8, split: test, run_id: run-{i}, as_of: 2026-09-01}}
---
## Hypothesis

Run {i} tests a bulk hypothesis about scaling.

## Setup

Same as the previous run with one change.

## Results

| metric | value | run |
|---|---|---|
| auroc | 0.80 | run-{i} |

## Interpretation

(human) Nothing surprising.

## Next

Continue the sweep.
"""

CONCEPT = """---
id: topic-{i}
type: concept
title: "Topic {i}"
created: 2026-09-02
updated: 2026-09-02
author: bob
status: active
tags: [bulk]
links: [topic-{next}]
sources: [EXP-20260901-run-{i}]
---
## Summary

Topic {i} summarises run {i}.

## Evidence

See [[EXP-20260901-run-{i}]].

## Open questions

None yet.

## Related

[[topic-{next}]] and [[DS-20260801-bulk]]
"""

IDEA = """---
id: IDEA-20261001-bulk-{i}
type: idea
title: "Idea {i}"
created: 2026-10-01
updated: 2026-10-01
author: bob
status: open
tags: [bulk]
links: []
---
Idea {i}: try a different learning rate schedule.
"""


def build_vault(root: Path, per_type: int = 1000) -> Path:
    make_vault(root, MIN_CONFIG)
    write(root, "protocols/EVAL-v1.md", PROTOCOL)
    write(root, "datasets/DS-20260801-bulk.md", DATASET)
    for i in range(per_type):
        nxt = (i + 1) % per_type
        write(root, f"experiments/EXP-20260901-run-{i}.md", EXPERIMENT.format(i=i))
        write(root, f"concepts/topic-{i}.md", CONCEPT.format(i=i, next=nxt))
        write(root, f"ideas/inbox/IDEA-20261001-bulk-{i}.md", IDEA.format(i=i))
    return root


def timed_lint(root: Path) -> tuple[float, float, list[Finding]]:
    """Wall and CPU seconds for one Vault.load + lint.run."""
    wall0, cpu0 = time.perf_counter(), time.process_time()
    findings = lint.run(Vault.load(root), today=TODAY)
    return time.perf_counter() - wall0, time.process_time() - cpu0, findings


@pytest.mark.slow
def test_lint_budget_on_3000_notes(tmp_path: Path) -> None:
    root = build_vault(tmp_path / "big")
    git(root, "init", "-q", "-b", "main")
    commit_all(root)
    # Untimed warm-up: endpoint antivirus scans each file on first open, which
    # dominates wall time on a freshly written vault and is not labbrain's cost.
    *_, findings = timed_lint(root)
    assert [f.to_dict() for f in findings if f.severity == ERROR] == []
    wall, cpu, _ = min((timed_lint(root) for _ in range(2)), key=lambda r: r[0])
    assert wall < 3.0, f"lint took {wall:.2f}s wall ({cpu:.2f}s CPU) on 3,000 notes"


@pytest.mark.slow
def test_validate_budget(vault_dir: Path) -> None:
    path = vault_dir / "experiments" / "EXP-20260901-baseline.md"

    def once() -> float:
        start = time.perf_counter()
        subprocess.run(
            [sys.executable, "-m", "labbrain", "validate", str(path)],
            check=True,
            capture_output=True,
        )
        return time.perf_counter() - start

    once()  # untimed warm-up (first-open file scanning, bytecode cache)
    best = min(once() for _ in range(3))
    assert best < 0.3, f"validate took {best * 1000:.0f} ms"
