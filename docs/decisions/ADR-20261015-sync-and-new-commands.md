---
id: ADR-20261015-sync-and-new-commands
type: decision
title: "labbrain sync and labbrain new"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, cli]
links: []
---
## For future agents

sync owns all derived state transitions; new owns ID minting and skeletons.
Skills should call these instead of editing frontmatter by hand.

## Context

The parent spec says "the tool" marks superseded notes and freezes protocols but assigns that to no command. It also relies on skills writing frontmatter by hand.

## Decision

labbrain sync is idempotent: it sets status and superseded_by on every note another note supersedes, and freezes draft protocols referenced by done experiments, using only transitions frozen-edit allows. Conflicting supersession is reported, never written. labbrain new mints an ID and writes a skeleton generated from the schema registries; every skeleton validates with zero findings.

Skip and conflict rules: a supersedes target that does not resolve is skipped, because broken-link reports it. A target whose type has no superseded_by field in its schema cannot be superseded, and is a conflict rather than a write. Two notes superseding the same note, a note already superseded by a different note, and a note that names itself in supersedes are conflicts. When a conflict message mentions an existing superseded_by value, it goes through the shared display_id helper, so the value is printed only when it names a note or is a valid ID for a configured note type with nothing identifier-like in it; anything else becomes a placeholder. Only a draft note of type protocol is frozen. Every write also sets updated to the current date taken from the engine's clock, and changes only the lines of the fields it sets: other values, including plain scalars such as yes, no or 12:30 that the read path types differently, are written back exactly as they were. A write that fails (a file that cannot be parsed for update or cannot be written) becomes an error finding for that note, and sync still applies the remaining changes.

## Alternatives considered

Leaving propagation to skills; new-id only.

## Consequences

sync-pending warns when sync was not run. Lint and sync share one plan: every sync-pending warning is a change sync would make, and its errors are the conflicts sync refuses to write. Covers spec ADR items 9 and 10.
