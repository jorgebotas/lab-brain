# Changelog

All notable changes to this project are documented here. Versions follow semantic versioning.

## 0.3.0 (unreleased)

### Added

- Claude Code hooks, shipped in the plugin (`hooks/hooks.json`) and run through
  `labbrain hook pre-tool-use | post-tool-use | session-start`:
  - a data guard that blocks any tool call that names a protected data path, or searches
    into one, through Read, Write, Edit, Glob, Grep, MCP tools and Bash (direct paths, `~`,
    `$HOME`, variables, `..`, symlinks, case, globs, `cd`, recursive searches, literal paths
    inside inline code). It judges what the call names, not what a program opens: see the
    README's known gaps;
  - guard self-protection: in a protected vault the agent may not change `.labbrain/`,
    `.copier-answers.yml`, `.claude/settings*.json`, the plugin or its caches, run
    `copier`, or start a nested agent CLI;
  - a frozen-file guard that blocks file-tool rewrites of frozen notes, existing `raw/`
    files and manuscripts outside `_proposals/`, using lint's `frozen-edit` comparison
    against git `HEAD`;
  - a PHI scan of the proposed content before a Write, Edit, MultiEdit or NotebookEdit in a
    protected vault, and `validate_path` after each, with errors shown to the agent. Writes
    made through Bash or MCP tools are not checked by the hooks (lint and pre-commit catch
    them);
  - a session brief: `index.md` is regenerated and `brief --short` is added to the session
    context.
- The pre-tool-use hook fails closed: bad input, an engine failure, a missing `uv`, a broken
  vault config or a check still running after 60 seconds all block the call. No hook ever
  emits an `allow` decision.
- Integration tests through the hook entry point, a warm-latency budget, the opt-in hooks
  smoke tests and `scripts/m5-gate.sh`.

### Changed

- The frozen-note policy table and comparison moved from the lint rule to
  `labbrain/frozen.py`, shared by lint and the frozen-file guard.
- `brief` passes note titles through `findings.sanitize`, because the short brief now feeds
  the session context.

### Upgrading from 0.2.0

- Update the plugin (`claude plugin update lab-brain@lab-brain`). The hooks need `uv` on
  `PATH`; without it every tool call in a session with the plugin enabled is blocked.
- Claude Code 2.1.295 or later is recommended, so a hook that times out also blocks.

## 0.2.0 (2026-10-20)

### Added

- Claude Code plugin: `.claude-plugin/plugin.json`, a single-plugin `marketplace.json`, and
  six skills (`brain-core`, `idea`, `exp-log`, `decide`, `handoff`, `brief`) that run the
  bundled engine through `uvx`.
- `labbrain tracker fetch` and `tracker diff`, with a `local` adapter that refuses any run
  path inside `data_paths`; the guard also compares file identity, so a differently-cased
  path on a case-insensitive filesystem cannot reach a protected data path.
- `labbrain exp record`: experiment notes from runs, with stamped headline metrics, a config
  diff against a parent, and a gate requiring a protocol and a dataset for finished runs.
- `labbrain finish` and `--finish` on `new` and `exp record`: validate, then sync, index and
  log in one step.
- `labbrain code sha` and `labbrain brief` (and `--short`).
- `--summary`, `--body`, `--tag` and `--status` on `new`. `--body` text goes under its own
  `## Notes` heading, so it never counts toward the three-line For-future-agents block; a
  `--body` with a level-2 heading and a `--summary` that is a heading are refused.
- `dataset_key` config option (default `data.dataset`).
- Opt-in headless smoke tests (`pytest -m smoke`), `scripts/m4-gate.sh`, and
  `claude plugin validate` in CI.

### Changed

- New notes are created exclusively, so two writers can never overwrite each other's note.
- `sync` lets a decision supersede its target only once it is `accepted`, and an experiment only
  once it is `done`.
- `exp record --into` replaces the Setup and Results blocks it wrote earlier (marked
  `<!-- labbrain:setup -->` and `<!-- labbrain:results -->`) instead of appending a second copy,
  so a running experiment can be recorded again when its runs finish.
- Skills attach quoted values to their options with `=` (`--title='<title>'`), so a value
  starting with `-` is no longer read as a flag.
- The smoke harness and `scripts/m4-gate.sh` set `UV_NO_CACHE=1`, because uv 0.7-0.10 may serve
  a stale `uvx --from <checkout>` build despite `cache-keys`.

### Fixed

- With `protected_data` on, `new` and `exp record` refuse (exit 2) a title, summary, body or
  hypothesis that matches a protected-data pattern, before writing anything.
- Refused with exit 2 instead of writing a broken note: a `--summary` that starts with a code
  fence, a `--body` with unbalanced code fences, a heading-like `--hypothesis`, and duplicate
  run IDs.
- Floats are written in a form that YAML 1.1 parsers also read as floats.
- A malformed run file is reported as an error instead of crashing the command.

## 0.1.0 (2026-10-16)

### Added

- `labbrain` Python package and CLI: vault discovery, configuration, frontmatter schemas for
  nine note types, collision-safe IDs, `vault root`, `config`, `new-id`, `new`, `validate`,
  `sync`, `index`, `log`, `list`, `links`, `config-hash`, `schema`, and a global `--vault`
  option.
- `labbrain lint` with sixteen rules, JSON and GitHub-annotation output, and `--base` for CI
  (a named base must resolve; only the default `HEAD` may be skipped).
- `labbrain phi-scan` with context-aware patterns, small-cell checks and a line-hash allowlist;
  UTF-16 and UTF-32 text files are decoded and scanned.
- `.pre-commit-hooks.yaml` exposing `labbrain-lint` and `labbrain-phi-scan`.
- Engine ADRs in `docs/decisions/`.

### Fixed

- Messages no longer echo a date-shaped run outside an ID's date stamp (`name-YYYYMMDD`,
  `MRN-YYYYMMDD-…`), which could be a date of birth. Only the configured dated-ID prefixes
  qualify.
- A byte-order mark at the start of the PHI denylist no longer hides its first name.
- Notes saved with a UTF-8 byte-order mark: their frontmatter is read (it was reported missing),
  frozen-edit compares them against git (it skipped them), frontmatter updates keep the mark, and
  lint and phi-scan agree on line-1 columns and allowlist hashes.
