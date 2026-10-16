---
id: EVAL-v2
type: protocol
title: "AUROC and ECE on the main split"
created: 2026-08-20
updated: 2026-09-02
author: alice
status: frozen
tags: [evaluation]
links: []
version: 2
changes_from: EVAL-v1
comparable_with: []
---
## Definition

Median one-vs-rest AUROC and expected calibration error (15 bins) on the test split of [[DS-20260801-main-split]].

## Changes from previous version

Replaces accuracy with AUROC and adds calibration; numbers are not comparable with [[EVAL-v1]].

## Known caveats

ECE depends on the bin count.
