---
id: ADR-20261019-local-tracker-adapter
type: decision
title: "local tracker adapter"
created: 2026-10-19
updated: 2026-10-19
author: claude
status: accepted
tags: [engine, plugin]
links: []
---
## For future agents

Run folders are `<runs_dir>/<run_id>/{config.yaml, metrics.json, meta.json}`.
Read `labbrain/trackers/local.py` before changing the layout.

## Context

`/exp-log` needs runs without a hosted tracker, and protected projects must never let a run path reach individual-level data.

## Decision

- **Protocol:** `TrackerAdapter` has `fetch` and `run_url`; `search` arrives in M7 with its first user.
- **Runs directory:** `runs_dir` is relative to `code_repo` when that is set, otherwise to the vault root; an absolute path is used as is.
- **Protected paths:** relative `data_paths` resolve against the vault root. Every opened path is canonicalised and refused if it lies in a data path, which also covers symlinked runs. The guard compares both the canonical paths and the file identity (`st_dev`, `st_ino`) of the path and each of its parents, because `resolve()` does not canonicalise letter case on case-insensitive filesystems (APFS, NTFS), and a differently-cased path got past the path comparison alone.
- **Run IDs** match `[A-Za-z0-9][A-Za-z0-9._-]*`.
- **Metrics:** only finite numbers are kept; a value too large for a float is dropped.
- **`meta.json` values** are type-checked, and a bad one is ignored. SHAs are lowercased and must match `[0-9a-f]{7,40}`.
- **Status:** the meta status, else `finished` with metrics, else `unknown`.
- **Messages** pass through `sanitize`.
- **`dataset_key`** (default `data.dataset`) sits beside `protocol_key`.

## Alternatives considered

- resolving `runs_dir` against the vault only: wrong for standalone vaults beside a code repo;
- checking only `runs_dir`: a symlinked run would escape;
- comparing canonical paths only: a case variant escapes on a case-insensitive filesystem;
- `display_id` for run IDs: it would blank every run ID.

## Consequences

The `none` backend and sweeps are deferred to M7, and `wandb`/`mlflow` report "arrives in a later engine version". Every opened path costs a few extra `stat` calls when `data_paths` is set.
