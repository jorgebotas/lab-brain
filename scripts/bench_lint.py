"""Benchmark Vault.load and lint on a synthetic 3,000-note vault. Not run in CI.

Builds 1,000 experiments, 1,000 concepts and 1,000 ideas (plus one protocol, one
dataset, and one figure per experiment embedded by bare filename) in a fresh git
repository under a temp directory, then reports best-of-N wall time (time.perf_counter)
and CPU time (time.process_time, all threads of this process; git subprocesses are not
counted) for:

- first load: Vault.load on a freshly generated vault (a new vault per run)
- warm load: Vault.load again on the same vault
- lint: lint.run on an already loaded vault, protected_data: true (PHI scan included)
- load + lint: both, warm

Usage: uv run python scripts/bench_lint.py [--per-type 1000] [--runs 3] [--dir PATH]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from labbrain import lint
from labbrain.vault import Vault

TODAY = date(2026, 10, 15)

CONFIG = """project_name: Bench
project_slug: bench
owner: alice
lab_members: [alice, bob]
agents: [claude, codex, gemini]
modality: image
protected_data: true
min_cell_size: 11
inbox_max_days: 30
"""

PROTOCOL = """---
id: EVAL-v1
type: protocol
title: "AUROC on the main split"
created: 2026-08-20
updated: 2026-08-20
author: alice
status: frozen
tags: [evaluation]
links: []
version: 1
comparable_with: []
---
## Definition

Median one-vs-rest AUROC on the test split of [[DS-20260801-main-split]].

## Changes from previous version

First version.

## Known caveats

None recorded.
"""

DATASET = """---
id: DS-20260801-main-split
type: dataset
title: "Public benchmark, main split"
created: 2026-08-01
updated: 2026-08-01
author: bob
status: active
tags: []
links: []
location: "s3://bench-bucket/benchmark/v1/"
extracted: 2026-08-01
protected: false
---
## Source

A public image classification benchmark, downloaded unchanged.

## Inclusion and exclusion

All images; no filtering.

## Split definition

The benchmark's official train and test split.

## Known issues

None recorded as of 2026-08-01.
"""

EXPERIMENT = """---
id: {id}
type: experiment
title: "Run {i}"
created: 2026-09-01
updated: 2026-09-02
author: alice
status: done
tags: [bench]
links: []
hypothesis: "Variant {i} reaches a usable AUROC"
protocol: EVAL-v1
tracker: {{backend: local, run_ids: [run-{i:04d}]}}
code: {{repo: "../model", sha: "1a2b3c4", dirty: false}}
dataset: DS-20260801-main-split
metrics:
  - {{name: auroc_median, value: 0.8{d}, split: test, run_id: run-{i:04d}, as_of: 2026-09-02}}
---
## Hypothesis

Variant {i} of the recipe reaches a usable AUROC on the main split.

## Setup

Default training recipe with seed {i}; see `train.py --variant {i}`.

```python
for epoch in range(30):
    train(model, lr=3e-4)  # [[not-a-link]]
```

## Results

| metric | value | run |
|---|---|---|
| auroc_median | 0.8{d} | run-{i:04d} |
| n | 40 | 3 |

![[roc-{i:04d}.png]]

## Interpretation

(human) Comparable to the baseline; see [[DS-20260801-main-split]].

## Next

Try label smoothing as in [[EVAL-v1]].
"""

CONCEPT = """---
id: {id}
type: concept
title: "Concept {i}"
created: 2026-09-15
updated: 2026-10-01
author: claude
status: active
tags: [calibration]
links: []
sources: [{exp}]
---
## For future agents

Synthesis of what this project knows about topic {i}.
Numbers here are copied from linked experiments; trust those notes over this page.

## Summary

Topic {i} regularises over-confident logits, which tends to improve calibration.
A second line of prose without any numbers at all, as most lines are.

## Evidence

AUROC reached 0.8{d} in [[{exp}]], as of 2026-09-12.
ECE fell to 0.04 at unchanged AUROC.

## Open questions

Does the effect survive a protocol change such as [[EVAL-v1]]?

## Related

[[{exp}]] · [[DS-20260801-main-split]]
"""

IDEA = """---
id: {id}
type: idea
title: "Idea {i}"
created: 2026-10-10
updated: 2026-10-10
author: bob
status: open
tags: [calibration]
links: []
---
Anneal the smoothing value to zero over training (variant {i}) and see whether
late-epoch calibration holds; compare with [[{exp}]].
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=bench", "-c", "user.email=bench@invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def build_vault(root: Path, per_type: int) -> Path:
    """Write the synthetic vault under `root` and commit it."""
    (root / ".labbrain").mkdir(parents=True)
    (root / ".labbrain" / "config.yaml").write_text(CONFIG)
    files: dict[str, str] = {
        "protocols/EVAL-v1.md": PROTOCOL,
        "datasets/DS-20260801-main-split.md": DATASET,
    }
    for i in range(per_type):
        exp = f"EXP-20260901-run{i:04d}"
        fields: dict[str, Any] = {"i": i, "d": i % 10, "exp": exp}
        files[f"experiments/{exp}.md"] = EXPERIMENT.format(id=exp, **fields)
        concept = f"concept-{i:04d}"
        files[f"concepts/{concept}.md"] = CONCEPT.format(id=concept, **fields)
        idea = f"IDEA-20261010-idea{i:04d}"
        files[f"ideas/inbox/{idea}.md"] = IDEA.format(id=idea, **fields)
        files[f"raw/figures/roc-{i:04d}.png"] = "not really a png\n"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", "bench")
    return root


def _timed(fn: Callable[[], Any]) -> tuple[float, float, Any]:
    wall, cpu = time.perf_counter(), time.process_time()
    result = fn()
    return time.perf_counter() - wall, time.process_time() - cpu, result


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--per-type", type=int, default=1000)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--dir", type=Path, default=None, help="parent for the temp vaults")
    args = parser.parse_args()
    os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ.setdefault("LABBRAIN_NOW", "2026-10-15T12:00:00")

    tmp = Path(tempfile.mkdtemp(prefix="labbrain-bench-", dir=args.dir))
    results: dict[str, list[tuple[float, float]]] = {}
    notes = findings = 0
    try:
        lint.load_rules()  # rule-module import cost is not part of any measurement
        vault_root = tmp
        for run in range(args.runs):
            vault_root = build_vault(tmp / f"v{run}", args.per_type)
            wall, cpu, vault = _timed(lambda r=vault_root: Vault.load(r))
            results.setdefault("first load", []).append((wall, cpu))
            notes = len(vault.by_rel)
        for _ in range(args.runs):
            wall, cpu, vault = _timed(lambda: Vault.load(vault_root))
            results.setdefault("warm load", []).append((wall, cpu))
        for _ in range(args.runs):
            wall, cpu, out = _timed(lambda: lint.run(vault, today=TODAY))
            results.setdefault("lint (loaded vault)", []).append((wall, cpu))
            findings = len(out)
        for _ in range(args.runs):
            wall, cpu, out = _timed(lambda: lint.run(Vault.load(vault_root), today=TODAY))
            results.setdefault("load + lint (warm)", []).append((wall, cpu))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"{notes} notes, {findings} findings, best of {args.runs} runs")
    print(f"{'measurement':<22} {'wall s':>8} {'cpu s':>8}   each run (wall/cpu)")
    for name, runs in results.items():
        wall = min(w for w, _ in runs)
        cpu = min(c for _, c in runs)
        detail = ", ".join(f"{w:.2f}/{c:.2f}" for w, c in runs)
        print(f"{name:<22} {wall:>8.3f} {cpu:>8.3f}   {detail}")


if __name__ == "__main__":
    main()
