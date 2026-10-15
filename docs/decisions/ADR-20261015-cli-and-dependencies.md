---
id: ADR-20261015-cli-and-dependencies
type: decision
title: "CLI framework, YAML handling and Python floor"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, cli]
links: []
---
## For future agents

Explains the dependency choices; check here before adding a runtime dependency.
Startup time matters because hooks call the CLI on every tool use.

## Context

Hooks will run labbrain validate on every write, lint must handle thousands of notes in under three seconds, and several lab members edit the same vault.

## Decision

argparse instead of typer, with heavy imports inside each command. Python 3.11 or newer. PyYAML's libyaml-backed safe loader for reads (ruamel's loader is pure Python since 0.19 and measured 6 s for 3,000 notes against 0.5 s for libyaml), and ruamel.yaml round-trip mode with Obsidian's indentation for writes, so a one-field edit is a one-line diff. Runtime dependencies are pydantic, PyYAML and ruamel.yaml. A global --vault option, also accepted after each subcommand, supports vaults in a subfolder of a code repo under pre-commit. Utility commands list, links, config-hash and schema, plus --format github and a .pre-commit-hooks.yaml, are part of the core.

Writes preserve what they did not mean to change: CRLF line endings, the file's permission bits, and list items written at zero indentation all survive an update. Duplicate frontmatter keys are rejected both on read and on update, with messages that name no values, because the two loaders would otherwise disagree on which duplicate wins. Writes must never produce YAML that the YAML 1.1 read path interprets differently from the YAML 1.2 write path, so any plain string that YAML 1.1 would read as another type is quoted on write. When validate is given an explicit --vault or LABBRAIN_VAULT that has no lab-brain config, it reports a configuration problem (exit 2) instead of treating the file as outside any vault. config-hash ignores the eight hash_ignore defaults listed in the plan (seed, output_dir, timestamp and run_name, each at top level and nested); the spec was aligned to that list.

## Alternatives considered

typer; ruamel for reads as well (too slow without its optional C extension); PyYAML for writes (destroys comments); surgical line patches.

## Consequences

Comment-preserving writes and fast reads use two loaders that must agree on values. Profiling put warm load plus lint, before the PHI rule, at about 1.1 s of CPU for 3,000 notes; a cold run took about 6.8 s of wall time, almost all of it on-access antivirus scanning of each first file open rather than engine work. The response is threaded file reads in Vault.load and in the PHI scan, a pruned directory walk for filename lookups, a fast path that skips link parsing on lines without a wikilink, and per-note caches of body lines, stem and type. The budget test times a warm, second load plus lint, so it measures the engine and not the host's file scanning. Covers spec ADR items 8, 11, 12 and 16.
