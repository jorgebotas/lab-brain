---
id: ADR-20261019-exp-record-and-finish
type: decision
title: "exp record and finish"
created: 2026-10-19
updated: 2026-10-19
author: claude
status: accepted
tags: [engine, plugin]
links: []
---
## For future agents

`exp record` decides status, protocol, dataset and code; skills only gather a hypothesis and
fill gaps. `finish` is the one end step for every writing skill.

## Context

Section 7 of the parent spec says /exp-log must refuse `done` without a protocol. The schema requires a dataset for `done`. Skills must not compute diffs or copy metrics by hand, and a skill's validate, index and log steps used to be three chained commands that permission rules could not approve.

## Decision

- **Status** from runs: failed > running or unknown > done.
- **The `done` gate** needs both a protocol and a dataset, each from a flag, a planned note or the runs, and each must exist as a note; disagreement between runs is an error.
- **`code`:** the runs' shared SHA, else `code sha` on `code_repo`, with the vault excluded from the dirty check; disagreeing SHAs record no code.
- **Metrics** are stamped with `run_id` and `as_of`. `split` is inferred only from a leading `train`/`val`/`valid`/`validation`/`test` segment. Each `as_of` date is a separate object, so the written YAML has no anchors or aliases.
- **`--into`** fills only planned or running notes, and appends to Setup and Results. The two appends and the frontmatter update are applied in memory and the note is written once, atomically. A frontmatter that cannot be updated exits 2 with `<id>: frontmatter cannot be updated`, and the note is left untouched.
- **`finish`** validates, and only when clean runs sync, index and log; `--finish` runs it in the same process.
- **Note creation is exclusive** with five ID retries, so parallel handoffs never overwrite each other. The note is written to a temp file and hard-linked into place (`os.link`). On a filesystem without hard links (`os.link` fails with EPERM, ENOTSUP, EOPNOTSUPP, EXDEV, EMLINK or ENOSYS) it falls back to an exclusive `open(O_CREAT|O_EXCL)`, which still never replaces a file.
- **`new --body`** text goes under its own `## Notes` heading after the For-future-agents block, so it never counts toward that block's three lines. A body line that is a level-2 heading, and a `--summary` that reads as a heading, are refused.
- **Exit codes** stay 0/1/2, with 2 for every refusal.

## Alternatives considered

- the skill computing diffs and metrics: not deterministic and not testable;
- exit 1 for refusals: it would conflict with "1 means findings";
- `os.replace` for new notes: it silently overwrites a racing writer;
- separate writes for the `--into` appends and the frontmatter: a failure between them leaves a half-filled note.

## Consequences

A finished run group without a dataset note cannot be logged as `done` until one exists. `--planned` notes record no code until `exp record --into`. On a filesystem without hard links, a crash in the middle of the exclusive write can leave a partial note.
