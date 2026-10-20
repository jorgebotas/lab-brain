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
Update with `claude plugin update lab-brain@lab-brain`. An installed plugin builds its engine
once per version; when you run the plugin from a local checkout, uv older than 0.11 may reuse
a stale build of it, which `UV_NO_CACHE=1` (or uv 0.11 or newer) avoids.

## Hooks

The plugin also installs four Claude Code hooks. They run the same engine through `uvx`, so
`uv` must be on `PATH`.

- **Data guard** (before every tool call): in a vault with `protected_data: true`, blocks any
  call that would read a `data_paths` entry, whether through Read, Glob, Grep, an MCP tool or
  a Bash command.
- **Frozen-file guard** (before writes): blocks rewrites of frozen notes, existing `raw/`
  files and manuscripts outside `manuscripts/_proposals/`. Notes not yet committed stay
  editable.
- **Write validator** (before and after writes): in a protected vault, blocks content that
  matches a PHI pattern before it is written; after each write, shows schema errors to the
  agent so it fixes them.
- **Session brief** (session start): regenerates `index.md` and adds the short brief to the
  session.

The guard fails closed. If the engine cannot start, `uv` is missing, the input is malformed
or the vault config does not load, the call is blocked. With a broken config the agent may
only read `.labbrain/`, so it can tell you what is wrong. The hooks never approve a call:
your own permission prompts still apply. Claude Code 2.1.295 or later is recommended, because
older versions let a call proceed when a hook times out.

What this means in practice:

- **You, not the agent, change the guard.** In a protected vault the agent may not edit
  `.labbrain/`, `.copier-answers.yml` or `.claude/settings*.json`, change the plugin, run
  `copier update`, or start another agent CLI. Make those changes yourself.
- **Analysis code reads data paths from config files.** A command that names a data path is
  blocked, so write `python train.py --config configs/a.yaml`, not
  `python train.py /data/rows.csv`.
- **Search a narrower folder.** A recursive search (`grep -r`, `find`, Glob, Grep) from a
  folder that contains a data path is refused. `rg` from a code repo whose data folder is
  gitignored is allowed.
- **Commit messages** go through `git commit -m "$(cat <<'EOF' … EOF)"` or `git commit -F`;
  other command substitutions can stand for any path, so they may be blocked.

Known gaps: the guard reads command text, so it cannot see what a program opens or prints
(by design: training runs read data), nor obfuscated or encoded paths, paths built inside
inline code, or hard links. Frozen notes edited through Bash or written by an MCP tool are
caught by lint and pre-commit, not by the hooks. For a stronger boundary, Claude Code's
OS-level Bash sandbox can deny reads of the data paths, at the cost of blocking training runs
in the session.

These guardrails make the safe path the default. They do not replace your institution's DUA,
IRB or security rules.

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
    scripts/m5-gate.sh                  # hooks smoke tests: data reads and frozen edits blocked

## Safety

The PHI guardrails make the safe path the default. They do not replace your institution's
DUA, IRB or security rules.
