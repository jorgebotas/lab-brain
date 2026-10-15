---
id: ADR-20261015-frozen-edit-semantics
type: decision
title: "frozen-edit semantics"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, lint]
links: []
---
## For future agents

Defines exactly what may change in a frozen note; the per-type table is in frozen_rules.py.
Check POLICIES there before changing which statuses freeze a note.

## Context

"Append-only" in the parent spec left open which diffs are allowed, and naive status handling let a note be unfrozen in one commit and rewritten in the next.

## Decision

A note is frozen according to its status at the base revision (protocols also when a done experiment references them). Only listed fields may change, and status may change only along a per-type transition table. The body may only gain lines (difflib opcodes equal and insert). Deleting a frozen note is an error; base versions are found by ID so moves are followed. raw/ files must stay byte-identical. The rule reads only files git reports as changed, through one batched cat-file process, and supports --base so CI can compare against the merge base. Without git, or with an unknown base, it emits one info finding and skips.

Messages name only field names and status values that the schema defines; a status outside the schema enum is shown as a placeholder, so a hand-edited status can never carry text into a message. A path where no repository can be opened counts as "without git" and gets the single info finding. A git failure after the rule has started is different: it becomes an error finding, so the rule fails closed instead of reporting a clean result it did not verify.

## Alternatives considered

Frontmatter-only checks, which let Results tables be rewritten; a total freeze, which blocks legitimate appended sections.

## Consequences

Typo fixes in frozen notes require supersession. A broken git installation or a corrupt object store blocks a commit rather than passing it silently. Covers spec ADR item 5.
