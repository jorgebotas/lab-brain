---
id: ADR-20261015-lint-rule-set
type: decision
title: "Lint rule set and rule ownership"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, lint]
links: []
---
## For future agents

Records how the parent spec's lint table was changed and why each condition has one owner.
Check this before adding a rule that overlaps an existing one.

## Context

The parent spec's rule table had three conditions owned by two rules each, which makes the gate "each broken fixture triggers exactly its rule" impossible. It also defined two heuristic rules over free prose.

## Decision

Two rules are added: missing-section (warning) and sync-pending (warning; conflicting supersession is an error). cross-protocol checks claims only, using structured frontmatter: a concept citing experiments under different protocols is normal and is not a comparison. undated-fact applies only to agent-authored concepts and claims, line by line. Ownership: a done experiment without a protocol is protocol-missing only; non-comparable evidence is cross-protocol only, while claim-stale covers superseded or failed evidence; an empty concept source list is concept-unsourced only, while the schema rule requires the key to exist.

cross-protocol skips a claim whose protocol does not resolve to a note, and skips evidence whose protocol does not resolve: broken-link owns unresolved references, and cross-protocol therefore never echoes an unresolved value. sync-pending reuses the plan computed by labbrain sync, so the rule and the command cannot drift apart: every sync-pending warning is a change sync would make, and its errors are the conflicts sync refuses to write. index-stale compares the regenerated index with the file on disk byte for byte. The undated-fact metric pattern accepts a number followed by a sentence-ending period, while a number followed by a word character, or by a period and then a word character, is not read as a metric; the stricter lookahead first proposed missed metrics at the end of a sentence.

## Alternatives considered

Prose scanning for cross-protocol and undated-fact; keeping the overlapping conditions.

## Consequences

Sixteen rules, each with a fixture mutation. A dangling protocol reference produces exactly one finding (broken-link), not a second one from cross-protocol. Covers spec ADR items 2, 3, 4, 6 and 15.
