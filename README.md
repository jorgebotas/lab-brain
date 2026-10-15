# lab-brain

Engine for lab-brain, a Claude Code–maintained second brain for ML research projects.

## Commands

    labbrain vault root                 # where am I?
    labbrain new experiment --title "Label smoothing" --author alice
    labbrain validate experiments/EXP-20261015-label-smoothing.md
    labbrain sync                       # propagate supersession, freeze referenced protocols
    labbrain index                      # regenerate index.md
    labbrain lint                       # all rules; --json or --format github for CI
    labbrain phi-scan .                 # PHI patterns and small cells
    labbrain list --type experiment --status running

Exit codes: 0 clean, 1 errors found, 2 usage or configuration problem.

## Development

    uv sync
    uv run pytest
    uv run pytest --cov --cov-fail-under=85

## Safety

The PHI guardrails make the safe path the default. They do not replace your institution's
DUA, IRB or security rules.
