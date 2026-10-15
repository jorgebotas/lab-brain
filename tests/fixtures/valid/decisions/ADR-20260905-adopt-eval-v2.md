---
id: ADR-20260905-adopt-eval-v2
type: decision
title: "Adopt EVAL-v2 for all new experiments"
created: 2026-09-05
updated: 2026-09-05
author: alice
status: accepted
tags: [evaluation]
links: [EVAL-v2]
---
## Context

Accuracy under EVAL-v1 hid calibration problems; see [[label-smoothing-calibration]] and [[LIT-szegedy2016-rethinking]].

## Decision

New experiments use [[EVAL-v2]].

## Alternatives considered

Keeping accuracy as the headline metric.

## Consequences

Numbers under EVAL-v1 and EVAL-v2 are not compared directly.
