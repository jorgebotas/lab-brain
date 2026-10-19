# lab-brain

Engine for lab-brain, a Claude Code–maintained second brain for ML research projects.

## Using the plugin

This repository is also a Claude Code plugin. In Claude Code:

    /plugin marketplace add jorgebotas/lab-brain
    /plugin install lab-brain@lab-brain

Skills (run inside a vault):

- `/lab-brain:idea <text>`: capture an idea in `ideas/inbox/`
- `/lab-brain:exp-log <run-id...> [--parent EXP-ID] [--into EXP-ID] [--planned]`: log runs as an
  experiment
- `/lab-brain:decide <summary>`: record a decision
- `/lab-brain:handoff`: write the session handoff
- `/lab-brain:brief`: where the project stands

Claude uses `brain-core` automatically when it works in a vault: its description triggers it.
The skills run the engine bundled with the plugin through `uvx`, so `uv` must be installed.
Update with `claude plugin update lab-brain@lab-brain`.

## Commands

    labbrain vault root                 # where am I?
    labbrain new experiment --title "Label smoothing" --author alice
    labbrain validate experiments/EXP-20261015-label-smoothing.md
    labbrain sync                       # propagate supersession, freeze referenced protocols
    labbrain index                      # regenerate index.md
    labbrain lint                       # all rules; --json or --format github for CI
    labbrain phi-scan .                 # PHI patterns and small cells
    labbrain list --type experiment --status running
    labbrain new idea --title "Cosine warmup" --author claude --summary "..." --finish "idea: Cosine warmup"
    labbrain finish ideas/inbox/IDEA-20261015-cosine-warmup.md --log "idea: Cosine warmup"
    labbrain tracker fetch run-1 run-2  # local runs as JSON
    labbrain tracker diff run-2 --parent EXP-20261001-baseline
    labbrain exp record run-2 --title "Lower LR" --author claude --protocol EVAL-v2 --dataset DS-20260801-main
    labbrain code sha                   # code repo commit and dirty flag
    labbrain brief                      # recent handoffs, open work, lint counts

Exit codes: 0 clean, 1 errors found, 2 usage, configuration or tracker problem, or a refused
write.

## Development

    uv sync
    uv run pytest
    uv run pytest --cov --cov-fail-under=85
    uv run pytest -m smoke              # headless skill runs; needs claude and ANTHROPIC_API_KEY
                                        # (or LABBRAIN_SMOKE_LOGIN=1 to use your login)
    scripts/m4-gate.sh                  # install from a local marketplace and run /lab-brain:brief

## Safety

The PHI guardrails make the safe path the default. They do not replace your institution's
DUA, IRB or security rules.
