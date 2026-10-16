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

Writes preserve what they did not mean to change: CRLF line endings, the file's permission bits, list items written at zero indentation, and the exact text of every value the update did not set all survive an update. Duplicate frontmatter keys are rejected both on read and on update, with messages that name no values, because the two loaders would otherwise disagree on which duplicate wins. Writes must never produce YAML that the YAML 1.1 read path interprets differently from the YAML 1.2 write path, so any plain string the tool writes (an updated value, or a skeleton field) that YAML 1.1 would read as another type is single-quoted. Values loaded from the file and left unchanged are dumped as they were, because re-quoting them would change their type on the read path. ruamel warnings are suppressed during updates, since they quote the YAML source. When validate, phi-scan or config-hash is given an explicit --vault or LABBRAIN_VAULT that has no lab-brain config, it exits 2 as a configuration problem instead of treating the files as outside any vault; one shared vault.find_root_or_none holds that policy. Every command that resolves a vault prints the engine-version warning once. An unexpected exception prints only "internal error" with the exception type and exits 2, without a traceback. When stdout is a closed pipe, commands that report findings keep their 0 or 1 exit code, so a truncated pipeline never turns a failure into a pass. Text output strips control and bidirectional-override characters from paths, rule names and list cells, and log entries keep to one line whatever the author or text contain. The sdist names what it ships (only-include), because hatchling ignores .git/info/exclude and would otherwise publish untracked working-tree directories. config-hash ignores the eight hash_ignore defaults listed in the plan (seed, output_dir, timestamp and run_name, each at top level and nested); the spec was aligned to that list.

## Alternatives considered

typer; ruamel for reads as well (too slow without its optional C extension); PyYAML for writes (destroys comments); surgical line patches.

## Consequences

Comment-preserving writes and fast reads use two loaders that must agree on values. An existing plain value that the two loaders read differently stays as it is: the engine never rewrites it, so its meaning on the read path is whatever the author wrote. Endpoint antivirus scanning dominated the first open of each file: the first load of 3,000 notes took 5.4 s of wall time, and about 1.2 s after file reads were made concurrent; a warm load plus lint takes about 1.4 s of wall time. Reads use a pool of min(8, cpu count) workers. The filename walk prunes dot-directories, so a file inside one no longer satisfies a bare embed. Other speedups are a fast path that skips link parsing on lines without a wikilink and per-note caches of body lines, stem and type. The budget tests time a warm, second run, so they measure the engine and not the host's file scanning. Covers spec ADR items 8, 11, 12 and 16.
