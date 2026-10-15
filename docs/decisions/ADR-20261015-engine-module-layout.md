---
id: ADR-20261015-engine-module-layout
type: decision
title: "Engine module layout"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine]
links: []
---
## For future agents

Records why the labbrain package differs from the tree in the parent spec.
Safe to rely on for module responsibilities; the code is the final word.

## Context

The parent spec sketches a single lint.py and no shared finding type. Fourteen-plus rules in one module, and two separate result types for lint and phi-scan, would be hard to test and review.

## Decision

Lint is a package whose rule modules register themselves and are discovered automatically. One Finding type (findings.py) serves lint, validate and phi-scan. Further modules beyond the parent tree: layout.py (constants and path predicates, standard library only), validate.py (single-file checks for the write hook), scaffold.py (labbrain new), sync.py, query.py (list and links), confighash.py, gitutil.py, and __main__.py.

Every Finding message passes through findings.sanitize when the Finding is built, so the leak guard sits in one place rather than in each rule. Within lint, Vault.load is the only reader of note files; rules, including phi, use the text it loaded. validate parses its one file directly, phi-scan reads each file once, and frozen-edit reads base versions from git. The shared helper notes.future_agents_end locates the leading agent block for both the schema checks and the index generator, so the two never disagree about where that block ends. One shared display_id helper in findings.py renders note IDs and link targets in every message and command output, and prints a value only when it is shaped like an ID.

## Alternatives considered

A single lint.py; separate finding classes per tool.

## Consequences

Adding a rule means adding a function in a rule module; nothing else changes. Because reads are centralised, file access is parallelised in two places, Vault.load and the PHI scan (see ADR-20261015-cli-and-dependencies for the measurements). Covers spec ADR items 1 and 16 (module part).
