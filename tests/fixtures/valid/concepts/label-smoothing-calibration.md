---
id: label-smoothing-calibration
type: concept
title: "Label smoothing and calibration"
created: 2026-09-15
updated: 2026-10-01
author: claude
status: active
tags: [calibration]
links: [CLM-20261001-median-auroc]
sources: [EXP-20260910-label-smoothing, LIT-szegedy2016-rethinking]
---
## For future agents

Synthesis of what this project knows about label smoothing and calibration.
Numbers here are copied from linked experiments; trust the experiment notes over this page.

## Summary

Label smoothing regularises over-confident logits, which tends to improve calibration.

## Evidence

ECE fell to 0.04 at unchanged AUROC in [[EXP-20260910-label-smoothing]], as of 2026-09-12.

## Open questions

Does the effect survive a protocol change such as [[EVAL-v1]] to [[EVAL-v2]]?

## Related

[[ADR-20260905-adopt-eval-v2]] · [[LIT-szegedy2016-rethinking]]
