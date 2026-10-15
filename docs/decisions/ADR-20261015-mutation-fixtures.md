---
id: ADR-20261015-mutation-fixtures
type: decision
title: "Mutation-based broken fixtures"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, testing]
links: []
---
## For future agents

Broken fixtures are functions in tests/fixtures/mutations.py, not directories.
Each mutation's docstring explains why only its rule fires.

## Context

One static broken vault per rule would mean many near-identical directories that drift from the valid fixture.

## Decision

The valid fixture is static; every broken variant is a named mutation applied to a git copy of it. The harness deletes index.md unless the mutation targets index-stale, and commits every mutation except frozen-edit ones, so frozen-edit sees a diff only when it should. Every linkable fixture note has at least two inbound links, so removing one never creates an orphan.

Fixture repositories are isolated from the developer's git setup: an autouse fixture removes the inherited repository-locating GIT_ variables (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE and similar), points global config at the null device and disables system config, and test commits skip hooks. A regression test runs a child pytest under a polluted git environment to prove it. Without it, running the suite from a hook or a rebase exec step could point fixture git commands at the outer repository or pick up user configuration.

## Alternatives considered

Static broken directories per rule.

## Consequences

The gate test asserts that the set of rules fired equals exactly the declared rule, and that every rule has a mutation. Parallel branches each append their own block to mutations.py; the union merge driver produced a broken file, so it was removed and such merges are resolved by keeping each branch's appended block. Covers spec ADR item 13.
