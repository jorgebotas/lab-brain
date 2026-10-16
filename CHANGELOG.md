# Changelog

All notable changes to this project are documented here. Versions follow semantic versioning.

## 0.1.0 (unreleased)

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
