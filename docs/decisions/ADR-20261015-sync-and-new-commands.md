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

Skip and conflict rules: a supersedes target that does not resolve is skipped, because broken-link reports it. A target whose type has no superseded_by field in its schema cannot be superseded, and is a conflict rather than a write. Two notes superseding the same note, or a note already superseded by a different note, are conflicts. When a conflict message mentions an existing superseded_by value, it goes through the shared display_id helper, so only an ID-shaped value is printed and anything else becomes a placeholder. Only a draft note of type protocol is frozen. Every write also sets updated to the current date taken from the engine's clock.

## Alternatives considered

Leaving propagation to skills; new-id only.

## Consequences

sync-pending warns when sync was not run. Lint and sync share one plan: every sync-pending warning is a change sync would make, and its errors are the conflicts sync refuses to write. Covers spec ADR items 9 and 10.
