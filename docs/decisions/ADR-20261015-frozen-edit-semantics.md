---
id: ADR-20261015-frozen-edit-semantics
type: decision
title: "frozen-edit semantics"
created: 2026-10-15
updated: 2026-10-20
author: claude
status: accepted
tags: [engine, lint]
links: []
---
## For future agents

Defines exactly what may change in a frozen note; the per-type table is in labbrain/frozen.py.
Check POLICIES there before changing which statuses freeze a note.

## Context

"Append-only" in the parent spec left open which diffs are allowed, and naive status handling let a note be unfrozen in one commit and rewritten in the next.

## Decision

A note is frozen according to its status at the base revision (protocols also when a done experiment references them). Only listed fields may change, and status may change only along a per-type transition table. The body may only gain lines (difflib opcodes equal and insert). Deleting a frozen note is an error; base versions are found by ID so moves are followed. New files under raw/ are allowed; an existing raw file is flagged only when its bytes differ, so a mode-only change passes, and deleting one is an error. The rule reads only files git reports as changed, through one batched cat-file process, and supports --base so CI can compare against the merge base. Only the default base may be skipped: without git, or in a repository with no commits yet, the default HEAD gets one info finding and the rule is skipped. A base the caller names must resolve; if it does not, or the vault is not in a repository, the CLI exits 2 and the rule, called as a library, reports an error, so a typo in a CI base can never pass as a clean check.

Messages name only field names and status values that the schema defines; a status outside the schema enum is shown as a placeholder, so a hand-edited status can never carry text into a message. When the vault sits in a subfolder of a repository, its prefix comes from git rev-parse --show-toplevel --show-prefix rather than from comparing paths, because a path-derived prefix failed open on a mis-cased path. A path where no repository can be opened counts as "without git". A git failure after the repository is opened is different: it produces one error finding, so the rule fails closed instead of reporting a clean result it did not verify. That includes resolving the base: resolve_ref treats only git's quiet "no such revision" answer as a missing base, and any other failure raises.

## Alternatives considered

Frontmatter-only checks, which let Results tables be rewritten; a total freeze, which blocks legitimate appended sections.

## Consequences

Typo fixes in frozen notes require supersession. A git command that fails after the repository was opened (for example a corrupt object store) blocks the commit rather than passing it silently. Covers spec ADR item 5.

**2026-10-20:** `POLICIES` and the comparison moved from `frozen_rules.py` to `labbrain/frozen.py`, which the lint rule and the M5 frozen-file guard both use. The semantics are unchanged.
