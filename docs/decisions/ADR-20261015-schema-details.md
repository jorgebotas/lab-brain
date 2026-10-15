---
id: ADR-20261015-schema-details
type: decision
title: "Schema details not fixed by the parent spec"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, schema]
links: []
---
## For future agents

Lists the schema choices made during implementation that the parent spec left open.
Check here before changing a status enum or how links resolve.

## Context

The parent spec gives no status values for literature and handoff notes, and does not say how notes are keyed or how links to files resolve.

## Decision

Literature status is active or stale; handoff status is final. Protocol version numbers are the only counter in the system. Notes are keyed by filename stem, so an id that disagrees with its filename fires only the schema rule. Wikilinks and embeds whose target contains a slash or a file extension resolve against the filesystem, not the ID map. Links are harvested even when a note fails model validation. Conditional requirements: dataset when an experiment is done, superseded_by when superseded, consolidated_into when an idea is consolidated, and the concept sources key.

The filesystem rule applies to body links only: references held in frontmatter fields always resolve as note IDs. When broken-link reports an unresolved target, it prints the target only if it is shaped like an ID (a letter or digit followed by up to 79 letters, digits, dots, underscores, slashes or hyphens), and otherwise a placeholder. Hash fields use fully anchored patterns, because pydantic-core matches a pattern anywhere in the string unless it is anchored. A note file that cannot be read is still loaded, as a note carrying a read error that the schema rule reports, so one unreadable file never aborts a run. Slugs for IDs drop combining marks, so accented letters keep their base letter, drop non-ASCII letters and digits that do not decompose, and turn any other non-ASCII character into a hyphen.

## Alternatives considered

Keying notes by the id field; treating every wikilink as an ID.

## Consequences

Renaming a file changes a note's ID. Some non-English names lose letters in their slug until a transliteration table is decided. Covers spec ADR items 14 and 18.
