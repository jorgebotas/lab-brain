---
id: ADR-20261019-skill-smoke-tests
type: decision
title: "skill smoke tests"
created: 2026-10-19
updated: 2026-10-19
author: claude
status: accepted
tags: [engine, plugin]
links: []
---
## For future agents

`uv run pytest -m smoke` needs `claude`, plus `ANTHROPIC_API_KEY` or `LABBRAIN_SMOKE_LOGIN=1`.
Record new findings about permission behaviour here.

## Context

The M4 gate needs headless `/idea` and `/exp-log` runs, and real model calls cost money and need credentials.

## Decision

- **Marker:** smoke tests carry the `smoke` marker, are deselected by default, and skip without `claude` or credentials.
- **Default isolation:** `claude --bare -p "/lab-brain:<skill> …" --plugin-dir <repo> --permission-mode dontAsk --allowedTools Read Edit Write --max-turns 15 --max-budget-usd 1`.
- **`LABBRAIN_SMOKE_LOGIN=1`:** runs without `--bare`, using the user's login and only project settings.
- **`LABBRAIN_SMOKE_ALLOW_ENGINE=1`:** also pre-approves the engine command, in case a skill's own `allowed-tools` is not honoured under `dontAsk`. The docs do not say whether it is; record the first real run's outcome here.
- **CI:** `smoke.yml` runs only on manual dispatch and only with the secret. `ci.yml` runs `claude plugin validate . --strict`, which needs no key, on Claude Code 2.1.289 or later.
- **Gate:** `scripts/m4-gate.sh` installs from a local marketplace path into a temporary `CLAUDE_CONFIG_DIR`, or prints a manual checklist and exits 3.

## Alternatives considered

A smoke job on every PR (cost per push); recorded transcripts (they would not exercise the real skill loader).

## Consequences

Automatic skill invocation (`brain-core`, `handoff`) is checked only by the manual checklist, because bare mode sends no skill listing.

**Observed 2026-10-20** (Claude Code 2.1.284, macOS, login mode `LABBRAIN_SMOKE_LOGIN=1` with `LABBRAIN_SMOKE_REQUIRED=1`, `LABBRAIN_SMOKE_ALLOW_ENGINE` unset):
- All three smoke tests passed: `idea`, `exp-log --parent`, and `exp-log` without a protocol.
- **A skill's own `allowed-tools` rule is honoured under `--permission-mode dontAsk`.** The engine calls ran with no permission denials, and the harness fails on any denial.

**Still unverified:**
- whether `--bare` loads the plugin from `--plugin-dir` (that needs `ANTHROPIC_API_KEY`; login mode does not use `--bare`);
- whether read-only `git` calls in the handoff skill are auto-allowed;
- whether a multi-line single-quoted `--body` matches the engine permission rule.

Record those outcomes here when they are observed.
