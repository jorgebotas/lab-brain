# lab-brain

Engine for lab-brain, a Claude Code–maintained second brain for ML research projects.

This repository currently contains `labbrain`, the deterministic Python core: schemas, IDs,
validation, lint and PHI scanning for lab-brain vaults. Skills, hooks and the plugin manifest
arrive in later releases.

## Development

    uv sync
    uv run pytest
    uv run labbrain --help

The PHI guardrails make the safe path the default. They do not replace your institution's
DUA, IRB or security rules.
