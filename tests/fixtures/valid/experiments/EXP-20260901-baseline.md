---
id: EXP-20260901-baseline
type: experiment
title: "Baseline classifier"
created: 2026-09-01
updated: 2026-09-02
author: alice
status: done
tags: [baseline]
links: []
hypothesis: "A plain ResNet reaches a usable AUROC on the main split"
protocol: EVAL-v2
tracker: {backend: local, run_ids: [run-001]}
code: {repo: "../toy-model", sha: "1a2b3c4", dirty: false}
config_hash: "sha256:3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b"
dataset: DS-20260801-main-split
metrics:
  - {name: auroc_median, value: 0.81, split: test, run_id: run-001, as_of: 2026-09-02}
---
## Hypothesis

A plain ResNet reaches a usable AUROC on the main split.

## Setup

Default training recipe; no parent experiment.

## Results

| metric | value | run |
|---|---|---|
| auroc_median | 0.81 | run-001 |

## Interpretation

(human) Good enough to serve as the comparison point.

## Next

Try label smoothing.
