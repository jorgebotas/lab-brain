# Changelog

All notable changes to this project are documented here. Versions follow semantic versioning.

## 0.1.0 (unreleased)

### Added

- `labbrain` Python package and CLI: vault discovery, configuration, frontmatter schemas for
  nine note types, collision-safe IDs, `new`, `validate`, `sync`, `index`, `log`, `list`,
  `links`, `config-hash`, `schema`.
- `labbrain lint` with sixteen rules, JSON and GitHub-annotation output, and `--base` for CI.
- `labbrain phi-scan` with context-aware patterns, small-cell checks and a line-hash allowlist.
- `.pre-commit-hooks.yaml` exposing `labbrain-lint` and `labbrain-phi-scan`.
- Engine ADRs in `docs/decisions/`.
