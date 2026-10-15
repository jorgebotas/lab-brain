---
id: ADR-20261015-phi-scan-design
type: decision
title: "PHI scanner design"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, phi]
links: []
---
## For future agents

Explains why PHI findings never contain text and how the allowlist is keyed.
Never add line text or matched values to scanner output.

## Context

The write hook feeds tool output back into model context, so any echoed text is a leak. Line-number allowlists break on every edit above the line, and hashing a short identifier on its own can be reversed by brute force.

## Decision

Findings report path, line, column, rule and span length only. Allowlist entries are keyed by file, rule and a SHA-256 of the whole stripped line. Validation errors are a second leak path, so pydantic errors are rendered without input values, YAML errors are reduced to a line number, and every message passes a sanitizer. Identifier patterns require nearby context words. A small inline count followed by a non-person unit word (seeds, folds and similar) is not flagged; samples is deliberately not exempt. phi-scan skips every dot-directory.

What may appear in a message: note IDs and vault-relative paths that identify notes or files; no other frontmatter value. The sanitizer caps its input before pattern matching so its cost stays bounded on very long input, and drops any token that straddles the cut, so a partial identifier cannot survive truncation. Pydantic error locations keep field names but mask dictionary keys and other non-field parts, and drop union branch tags, because a key can itself be sensitive text; config validation errors are masked the same way. The CLI prints only exception messages, never tracebacks or chained causes, since a chained YAML error can quote file content.

The scanner reads each file once, and the phi rule inside lint scans the text Vault.load already loaded. Concurrent disk reads keep a bounded window of reads in flight and cancel the rest on the first error, so memory stays bounded on large vaults. It fails closed: a file that cannot be read yields an error finding saying the file could not be scanned, and a denylist that cannot be read is a configuration error. Symlinked directories inside the vault are followed with loop protection; a link that points outside the vault, or that cannot be inspected, fails closed with an error finding instead of being skipped. Links into directories the scan otherwise skips are followed deliberately, so content cannot hide behind a link. Record-number context follows the spec's list: MRN, medical record, record no, record number, record #, patient id written with a space, underscore or hyphen, and chart. A bare "record" is not a context word, because ordinary prose uses it constantly. The small-cell check parses each number whole, including thousands separators and decimals, so a large or fractional figure is never read as a small count.

## Alternatives considered

The parent spec's file, line and rule allowlist key; redacted line excerpts in output.

## Consequences

Reviewing a finding means opening the file. A file the scanner cannot read blocks the commit until it is fixed or excluded. The engine repository scans itself: a test runs the scanner over every git-tracked file except tests/ and docs/superpowers/, so these ADRs and the README must pass it. Covers spec ADR items 7 and 17.
