---
id: EXP-20260910-label-smoothing
type: experiment
title: "Label smoothing vs. calibration"
created: 2026-09-10
updated: 2026-09-12
author: claude
status: done
tags: [calibration]
links: [EXP-20260901-baseline]
hypothesis: "Label smoothing improves calibration without lowering AUROC"
protocol: EVAL-v2
tracker: {backend: local, run_ids: [run-002]}
code: {repo: "../toy-model", sha: "5e6f7a8", dirty: false}
config_hash: "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
dataset: DS-20260801-main-split
metrics:
  - {name: auroc_median, value: 0.81, split: test, run_id: run-002, as_of: 2026-09-12}
  - {name: ece, value: 0.04, split: test, run_id: run-002, as_of: 2026-09-12}
---
## For future agents

One run comparing label smoothing against [[EXP-20260901-baseline]] under EVAL-v2.
Safe to rely on the metrics block; check the protocol before comparing elsewhere.

## Hypothesis

Label smoothing improves calibration without lowering AUROC.

## Setup

Diff vs. [[EXP-20260901-baseline]]: `train.label_smoothing` set to a small positive value.

## Results

| metric | value | run |
|---|---|---|
| auroc_median | 0.81 | run-002 |
| ece | 0.04 | run-002 |

## Interpretation

(agent interpretation, unreviewed) Calibration improved at no AUROC cost.

## Next

Check whether the effect holds at other smoothing values.
