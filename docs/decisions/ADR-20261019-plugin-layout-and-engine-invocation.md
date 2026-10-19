---
id: ADR-20261019-plugin-layout-and-engine-invocation
type: decision
title: "plugin layout and engine invocation"
created: 2026-10-19
updated: 2026-10-19
author: claude
status: accepted
tags: [engine, plugin]
links: []
---
## For future agents

The plugin is this repo. Skills call `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain`; change the
string in every skill and in `tests/test_plugin_manifest.py` together.

## Context

The parent spec asks for a single-plugin marketplace in the engine repo. Skills must call an engine of the same version as themselves. `${CLAUDE_PLUGIN_ROOT}` is substituted in SKILL.md text, but is not set in Bash. Plugin `bin/` directories come after the user's PATH and block claude.ai/Cowork installs.

## Decision

- `.claude-plugin/plugin.json` (version `0.2.0`, kept equal to `pyproject.toml` by a test) and `marketplace.json` with one entry, `source: "./"`, live at the repo root.
- Skills are in `skills/<name>/SKILL.md`; there is no `commands/` and no `bin/`.
- Every skill runs the engine as `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain`. It pre-approves that string in `allowed-tools`, both quoted and unquoted, because permission rules match the command text.
- Skills never assign shell variables or use command substitution, because allow rules do not match past an assignment.
- User text is single-quoted.
- `[tool.uv] cache-keys` lists `pyproject.toml` and `labbrain/**/*.py`, because without it `uvx --from <checkout>` serves a stale build; this was verified with uv 0.7.17.

## Alternatives considered

- a `bin/labbrain` shim: it is shadowed by a user's own `labbrain`, and blocks claude.ai/Cowork installs;
- the vault's pinned uvx command: the engine version would follow the vault, not the skills;
- prose-only skills: they contradict the spec's rule that deterministic logic lives in Python.

## Consequences

- The first skill call downloads dependencies from PyPI.
- Each plugin version builds its own engine.
- A vault's `CLAUDE.md` keeps its own pinned command for humans and pre-commit, and `engine_min_version` warns when either copy is too old.
- `pyproject.toml` now holds a static `version = "0.2.0"` instead of a dynamic hatch version, so the manifest test can compare it with `labbrain.__version__` and `plugin.json`.
- `uv.lock` also records the package version, so a version bump needs `uv lock`; CI's `uv sync --locked` fails on a missed one.
