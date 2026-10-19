# lab-brain plugin and capture skills (M4) — Design

Date: 2026-10-19 · Status: approved in brainstorming; awaiting written-spec review
Parent spec: *lab-brain: ML Research Second Brain — Implementation Spec* (2026-10-13), sections 3, 7, 9, 11, 12 (M4).
Builds on: engine v0.1.0 (`docs/superpowers/specs/2026-10-15-labbrain-core-design.md`) and template v0.1.0 (`jorgebotas/lab-brain-template`).

## 1. Scope and decisions

**In scope:**

- The Claude Code plugin served from this repo: `plugin.json`, a single-plugin `marketplace.json`, and six skills: `brain-core`, `idea`, `exp-log`, `decide`, `handoff`, `brief`.
- The engine commands those skills need: `tracker fetch`, `tracker diff`, `exp record`, `code sha`, `brief`, and new flags on `new`.
- The tracker adapter protocol plus the `local` adapter.
- Unit tests, a manifest test, opt-in headless smoke tests, an M4 gate script, CI changes and ADRs.
- Release as engine v0.2.0, then a follow-up template v0.2.0 (section 10).

**Out of scope:**

- Hooks (M5). Nothing in `hooks/` is created.
- `/exp-log --sweep`, which moves to M7 with W&B; the local adapter has no real sweep concept.
- The `wandb` and `mlflow` adapters (M7).
- The other six skills (M6) and `/import`.
- A `bin/` directory, which would block claude.ai and Cowork installs.
- `commands/`, which the current docs call the legacy format.

**Decisions taken in brainstorming:**

| Question | Decision |
| --- | --- |
| How engine and plugin ship | One branch and one PR on `jorgebotas/lab-brain`, released together as v0.2.0 |
| `/exp-log` scope | Run IDs, `--parent` and `--planned`; `--sweep` deferred to M7 |
| How skills call the engine | `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain …`, so the engine is always the installed plugin's version |
| Template | Follow-up template v0.2.0: pin engine v0.2.0, offer the plugin from the generated settings, plus the v0.1.1 backlog |
| Smoke tests | Opt-in pytest marker using `claude --bare -p` and `ANTHROPIC_API_KEY`, plus a manual-trigger CI job that runs only if the secret exists |

**Facts from the current Claude Code docs, checked 2026-10-19:**

- `plugin.json` and `marketplace.json` can share the repo's `.claude-plugin/` directory, with the marketplace entry `source: "./"`. Only `name` is required in `plugin.json`.
- Plugin skills live in `skills/<name>/SKILL.md` and are invoked as `/<plugin>:<skill>`, e.g. `/lab-brain:idea`. The bare form works when nothing else claims the name.
- `${CLAUDE_PLUGIN_ROOT}` is substituted inline in SKILL.md bodies and in `allowed-tools` Bash rules. It is not an environment variable for Claude's Bash tool.
- Python dependencies are not installed automatically. uvx installs them, from PyPI, on the first call.
- If `version` is set in `plugin.json`, users update only when it is bumped. `claude plugin validate` checks both manifests.
- `claude -p "/plugin:skill args"` expands the skill. `--bare` skips user plugins, settings, CLAUDE.md and memory, and needs `ANTHROPIC_API_KEY`.

## 2. Repository layout (changes only)

```
lab-brain/
  .claude-plugin/
    plugin.json            # new
    marketplace.json       # new
  skills/                  # new
    brain-core/SKILL.md
    idea/SKILL.md
    exp-log/SKILL.md
    decide/SKILL.md
    handoff/SKILL.md
    brief/SKILL.md
  labbrain/
    trackers/              # new
      __init__.py          # get_adapter(config, root) -> TrackerAdapter
      base.py              # RunRecord, TrackerAdapter, TrackerError
      local.py             # LocalAdapter
    experiments.py         # new: record(), config_diff(), render_setup(), render_results()
    brief.py               # new: build_brief(vault, short) -> str
    codeinfo.py            # new: code_sha(path) -> CodeInfo
    scaffold.py            # changed: body/summary/tags/status for `new`
    cli.py                 # changed: new subcommands and flags
  scripts/
    m4-gate.sh             # new
  tests/
    fixtures/runs/         # new: synthetic local runs
    test_trackers_local.py
    test_experiments.py
    test_codeinfo.py
    test_brief.py
    test_new_flags.py
    test_plugin_manifest.py
    smoke/
      conftest.py          # skip unless ANTHROPIC_API_KEY and `claude` exist
      test_smoke_skills.py
  .github/workflows/
    ci.yml                 # changed: plugin-validate job
    smoke.yml              # new: workflow_dispatch only
  docs/decisions/          # four new ADRs (section 9)
```

## 3. Plugin manifests and engine invocation

**`.claude-plugin/plugin.json`**

```json
{
  "name": "lab-brain",
  "version": "0.2.0",
  "description": "Skills for lab-brain research vaults: capture ideas, log experiments, record decisions, hand off sessions.",
  "author": { "name": "jorgebotas" },
  "repository": "https://github.com/jorgebotas/lab-brain",
  "license": "MIT"
}
```

**`.claude-plugin/marketplace.json`**

```json
{
  "name": "lab-brain",
  "description": "Single-plugin marketplace for the lab-brain engine.",
  "owner": { "name": "jorgebotas" },
  "plugins": [ { "name": "lab-brain", "source": "./" } ]
}
```

**Version and licence.**

- `version` appears only in `plugin.json`, never in the marketplace entry. A test keeps it equal to `pyproject.toml` and `labbrain.__version__`.
- `license` and `author` match `pyproject.toml` (`MIT`, `jorgebotas`); the manifest test checks both.

**Install.**

1. `/plugin marketplace add jorgebotas/lab-brain`. Append `@v0.2.0` to pin a tag.
2. `/plugin install lab-brain@lab-brain`.
3. Update from the shell with `claude plugin update lab-brain@lab-brain`, or by turning on auto-update for the marketplace.

**Engine command.**

- Every skill body writes the engine as the exact string `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain`. This document calls it `ENGINE`.
- Every skill's `allowed-tools` includes `Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)`, so engine calls run without a permission prompt.
- The engine finds the vault as it does today: `--vault`, then `LABBRAIN_VAULT`, then the nearest ancestor holding `.labbrain/config.yaml`.
- A vault's own `CLAUDE.md` keeps its pinned uvx command for humans and pre-commit. Both copies of the engine warn through `engine_min_version` when they are too old.

## 4. Engine additions

### 4.1 Tracker protocol (`labbrain/trackers/base.py`)

`RunRecord` is the `TypedDict` from parent spec section 9, with these fields:

- `run_id`, `name`, `url`
- `status` (`running | finished | failed | unknown`)
- `started_at`, `ended_at`
- `config`, flattened with dot keys
- `summary` (`dict[str, float]`)
- `tags`, `git_sha`, `git_dirty`, `notes`

`TrackerAdapter` is a `Protocol` with `name`, `fetch(run_ids)`, `search(filters, limit=20)` and `run_url(run_id)`. `TrackerError(Exception)` carries a message that is safe to print.

`get_adapter(config, root)` maps `tracker.backend` to an adapter:

| Backend | Result |
| --- | --- |
| `local` | `LocalAdapter` |
| `wandb`, `mlflow` | `TrackerError("tracker backend '<name>' arrives in a later engine version")` |
| `none` | `TrackerError("tracker backend is 'none': ask the user for metric values")` |
| anything else | `TrackerError("unknown tracker backend")` |

The backend name is printed only when it is one of the known names.

### 4.2 Local adapter (`labbrain/trackers/local.py`)

**Runs directory.**

- An absolute `tracker.runs_dir` is used as is, after expanding `~`.
- A relative one resolves against `code_repo` when `code_repo` is set, otherwise against the vault root. A relative `code_repo` itself resolves against the vault root.
- The resolved directory is canonicalised (symlinks, `..`).
- If it lies inside any canonicalised `data_paths` entry, every call raises `TrackerError("runs_dir is inside a protected data path")`.

**Run IDs.** An ID must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`. Anything else raises `TrackerError("invalid run id")` and the ID is not echoed.

**Files per run** (`<runs_dir>/<run_id>/`):

| File | Required | Use |
| --- | --- | --- |
| `config.yaml` | yes | YAML mapping, flattened to dot keys. Nested mappings recurse; lists and scalars are kept as values. |
| `metrics.json` | no | JSON object, flattened. Keeps only `int` and `float` values that are not `bool` and are finite, as floats. |
| `meta.json` | no | Optional keys `name`, `status`, `started_at`, `ended_at` (ISO 8601), `tags`, `git_sha`, `git_dirty`, `notes`, `url`. Unknown keys are ignored. |

**Status.** A valid `meta.json` `status` wins. Otherwise a run is `finished` if `metrics.json` exists, and `unknown` if not.

**Errors.** A missing run directory or `config.yaml` raises `TrackerError("run <id>: config.yaml not found")`. Unparsable YAML or JSON raises `TrackerError("run <id>: <file> is not valid <YAML|JSON>")`. No file content is ever included in a message.

**`search(filters, limit)`.** Accepted filter keys are `tags` (all must be present) and `status` (equality). Results are sorted newest first by `started_at`; a missing `started_at` sorts last, then by run ID. There is no CLI for `search` in M4. It exists to complete the protocol and is unit-tested.

**`run_url`.** Returns `meta.json`'s `url`, or `None`.

### 4.3 `labbrain tracker fetch RUN... [--json]`

- Prints a JSON array with one object per requested run, in request order. `--json` is the default and only format.
- Each object is the `RunRecord`, with datetimes as ISO strings, plus three derived keys:
  - `config_hash`: `labbrain.confighash` over `config`, honouring `hash_ignore`.
  - `protocol`: `config[protocol_key]` as a string, or `null`.
  - `headline`: the `summary` items whose names match any `headline_metrics` pattern (`fnmatch`), or all of `summary` when `headline_metrics` is empty.
- Exit codes: 0 on success; 1 on `TrackerError`, with the message on stderr; 2 when the vault is not found.

### 4.4 `labbrain tracker diff RUN... --parent EXP-ID [--format md|json]`

Steps:

1. The parent must be an experiment note in the vault with a non-empty `tracker.run_ids`. If not, exit 1 with `parent <EXP-ID> has no run ids`, or `parent not found`.
2. Fetch the parent's runs and the given runs through the configured adapter.
3. Compute the *common config* of each group: the keys present in every run of the group with equal values. Keys matching `hash_ignore` are dropped first.
4. Compare the given runs' common config with the parent's:
   - `added`: keys only in the child;
   - `removed`: keys only in the parent;
   - `changed`: keys in both with different values, as `{from, to}`.
5. `varied` lists the keys that are present in only some of the given runs, or that differ between them.

The JSON output is `{"parent": "<EXP-ID>", "added": {...}, "removed": {...}, "changed": {"k": {"from": v, "to": v}}, "varied": ["k", ...]}`, with keys sorted.

The `md` output is the default. It is a Setup block:

```
Config diff against [[EXP-...]] (hash_ignore keys omitted):

| key | parent | this |
| --- | --- | --- |
| optim.lr | 0.001 | 0.0003 |
| model.dropout | — | 0.1 |

Varied across these runs: seed_group, data.fold.
```

- Values are rendered with `json.dumps`, compact.
- `—` marks an absent key.
- Rows are sorted by key.
- With no differences, the block is the single line `Same config as [[EXP-...]] (hash_ignore keys omitted).`
- The `Varied` line is omitted when `varied` is empty.

### 4.5 `labbrain exp record RUN... --author A (--title T | --into EXP-ID) [--parent EXP-ID] [--protocol P] [--hypothesis H] [--link ID]...`

This command creates an experiment note from runs, or fills in a planned or running one. It prints the note's vault-relative path. It is implemented in `labbrain/experiments.py` and writes atomically, as the existing `new` does.

**Frontmatter it sets:**

| Field | Value |
| --- | --- |
| `tracker` | `{backend: <config backend>, run_ids: [RUN...], url: <first run_url or null>}` |
| `config_hash` | The shared hash when every run has the same `config_hash`; otherwise `null` (the Setup then lists the varied keys) |
| `protocol` | `--protocol` if given; otherwise the shared `protocol` of the runs. Exit 1 if the runs disagree (`runs disagree on protocol; pass --protocol`). Exit 1 if the chosen ID is not a protocol note in the vault (`protocol <ID> not found`). |
| `code` | `repo`: `code_repo` or `null`. `sha`: the runs' shared `git_sha`; otherwise, when `code_repo` is a git repo, the `code sha` result; otherwise `null`. `dirty`: `true` if any run or the `code sha` result is dirty. If no source gives a SHA, `code` stays `null`. |
| `metrics` | One entry per run per headline metric: `{name, value, split, run_id, as_of: today}`. `split` is the first `/`- or `.`-separated segment of the name when that segment is one of `train`, `val`, `valid`, `validation`, `test`, otherwise `null`. `name` is kept as given. |
| `status` | Any run `failed` → `failed`. Else any `running` or `unknown` → `running`. Else (all `finished`) → `done`. |
| `hypothesis` | `--hypothesis`, if given |
| `links` | `--parent` and each `--link`, deduplicated |
| `updated` | Today (`LABBRAIN_NOW` honoured) |

**Protocol gate.** If the resulting status is `done` and no protocol was found, the command exits 1 with `protocol required to record finished runs: pass --protocol EVAL-vN or set <protocol_key> in the run config`. Nothing is written.

**Body.**

- `## Hypothesis` gets `--hypothesis` when given.
- `## Setup` gets the `tracker diff` md block when `--parent` is given. Otherwise it gets `Runs: run-a, run-b.` followed by the `Varied across these runs: …` line when that applies.
- `## Results` gets a table `| metric | value | split | run |` with one row per metric entry.
- `## Interpretation` and `## Next` are left empty.

**`--into`.**

- The target must be an experiment whose status is `planned` or `running`. Otherwise exit 1: `<ID> is <status>; only planned or running experiments can be filled in`.
- `tracker`, `config_hash`, `protocol`, `code`, `metrics`, `status` and `updated` are set as in the table, replacing whatever the planned note held. `links` gains the new IDs and keeps the existing ones. `title`, `created`, `author` and `tags` are kept. An existing `hypothesis` is kept unless `--hypothesis` is given.
- The Setup and Results blocks are appended under their headings, after any existing text in that section. Nothing else in the body changes.
- `--title` is not allowed with `--into`.

**Errors.** Tracker errors propagate with exit 1. Vault not found gives exit 2.

### 4.6 `labbrain code sha [--repo PATH]`

- Prints `{"repo": "<as given or configured>", "sha": "<40 hex>", "dirty": true|false}`.
- The default repo is `code_repo`, resolved against the vault root.
- `dirty` means `git status --porcelain` is non-empty; untracked files count.
- Exit 1 with `code repo not set` when there is no repo. Exit 1 with `not a git repository` when the path is not inside a work tree. Uses `labbrain/gitutil.py`.

### 4.7 `labbrain brief [--short]`

Built from a loaded `Vault` plus a lint run. It prints note IDs and titles (what `index.md` already holds), never body text.

**Full form**, under 40 lines:

```
<project_name> · engine <version>
<version warning line, if any>

Recent handoffs:
  HO-20261019-1420-claude  <title>
  (up to 3, newest ID first; "  none" if empty)

Experiments running (N):
  EXP-...  <title>
  (up to 5, newest ID first; "  … and K more" beyond)
Experiments planned (N):
  (same shape)
Stale claims (N):
  (same shape)

Open ideas: N · Lint: E errors, W warnings
```

**`--short`**, at most 10 lines; the M5 SessionStart hook will call it:

```
<project_name> · engine <version>
<version warning line, if any>
Last handoff: HO-...  <title>            (or "Last handoff: none")
Running N · Planned N · Stale claims N · Open ideas N · Lint errors E
```

Exits 0 even when lint has errors; it only reports them. Exit 2 when the vault is not found.

### 4.8 New flags on `labbrain new`

| Flag | Effect |
| --- | --- |
| `--summary TEXT` | Replaces the For-future-agents placeholder line, for agent authors only. Ignored with a stderr note for human authors, whose notes have no such block. |
| `--body TEXT` | Inserted after the For-future-agents block and before the required section headings. A trailing newline is added. |
| `--tag TAG` (repeatable) | Fills `tags`, deduplicated, in order given. |
| `--status STATUS` | Must be a valid status for the type, or argparse exits 2. Sets the initial status. |

## 5. Skills

**Shared rules.**

- **Frontmatter:** each skill has `name`, `description`, `argument-hint` where it takes arguments, and an `allowed-tools` line containing at least `Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)`. No skill sets `disable-model-invocation`.
- **Narrow descriptions:** every skill except `brain-core` has one, of the form "Use only when the user explicitly asks to …". `handoff` and `brief` also name the situations where Claude may invoke them itself.
- **Body:** a numbered procedure, the exact ENGINE commands, and a "Do not" list.
- **Author:** agent-written notes use `--author claude`, and handoffs use `--agent claude`.
- **Finishing a write:** every writing skill ends with one chained Bash command:

  `ENGINE validate <path> && ENGINE index && ENGINE log "<skill>: <one-line summary>" --author claude`

  If `validate` fails, the skill fixes the reported fields and runs the chain again. A skill never ends with a note that fails validation.
- **Shared "Do not" list:**
  - never edit `index.md`, anything under `raw/`, or a frozen note;
  - never invent IDs, hypotheses, protocols or metric values;
  - never paste text that `phi-scan` matched;
  - never write outside the vault.

| Skill | Description trigger | Procedure |
| --- | --- | --- |
| `brain-core` | Any session whose working directory is inside a lab-brain vault, or when the user talks about the vault's experiments, ideas, decisions, protocols or handoffs | At most 80 lines, writes nothing. Covers: find the vault with `ENGINE vault root`; read `ENGINE config` for `protected_data` and `search`; a compressed write-rules table; IDs come only from `new`/`new-id`; the freshness rule (copied numbers carry a run ID or as-of date); PHI rules when protected; read `index.md` before searching; use qmd only when `search: qmd`; point to the other skills. |
| `idea` | User explicitly asks to capture or jot down an idea | Asks no questions and finishes in one Bash call: `p=$(ENGINE new idea --title "<first sentence, ≤80 chars>" --author claude --summary "<first sentence>" --body "<full text>" [--tag t]...) && ENGINE validate "$p" && ENGINE index && ENGINE log "idea: <title>" --author claude`. Tags are inferred only from words already in the text. |
| `exp-log` | User explicitly asks to log runs or an experiment | 1. `ENGINE tracker fetch RUN...`. 2. Hypothesis: from run tags or notes if one is stated there; otherwise ask the user and never invent it. 3. Protocol: the fetched `protocol`; otherwise ask the user, showing `ENGINE list --type protocol` as the options, and never invent it. 4. `ENGINE exp record RUN... --author claude --title "…" [--parent EXP] [--protocol P] --hypothesis "…"`; if a planned note for these runs exists (the user names it, or `ENGINE list --type experiment --status planned`), use `--into` instead of `--title`. 5. Write `## Interpretation` only if the user asked, starting with `(agent interpretation, unreviewed)`. 6. Finish the write. **`--planned`:** ask for the hypothesis, then `p=$(ENGINE new experiment --title "…" --author claude --summary "…")`, set `hypothesis` in frontmatter and in `## Hypothesis`, and describe the planned setup under `## Setup`. A later `/exp-log RUN --into <ID>` fills it in. |
| `decide` | User explicitly asks to record a decision or ADR | 1. Draft Context, Decision and Consequences from the conversation. 2. If no alternatives were discussed, ask for them. 3. `p=$(ENGINE new decision --title "…" --author claude --summary "…" --status accepted)`, or `--status proposed` when the user calls it a proposal. 4. Fill in the four sections. 5. If it reverses an earlier ADR (the user names it, or `ENGINE list --type decision`), set `supersedes: <ADR-ID>` and run `ENGINE sync`. Never edit the old ADR by hand. 6. Finish the write. |
| `handoff` | User asks for a handoff, a session is ending, the work is passing to another agent, or a subagent is finishing delegated vault work | 1. Run `git status --short` and `git diff --stat` in the vault, and in `code_repo` if it is set and exists. These are pre-approved via `allowed-tools: Bash(git status*), Bash(git diff --stat*)`. 2. `p=$(ENGINE new handoff --title "…" --author claude --agent claude --summary "…")`. 3. Set `session_goal` and `files_touched` (vault-relative and code-repo paths from step 1). 4. Fill in Done, In progress, Blockers and "Next step for whoever picks this up", linking note IDs. 5. Finish the write. |
| `brief` | User asks "where are we", for a status or briefing, or a session starts in a vault | Run `ENGINE brief` and show its output verbatim. Writes nothing. |

## 6. Error handling and output safety

- Engine messages keep the v0.1.0 rule: they name files, IDs, field names and schema values, never file contents or frontmatter values. They never print tracebacks; unexpected exceptions go through the existing top-level handler.
- **Echoed values.** `tracker fetch` and `tracker diff` deliberately print run config and metric values, which is their purpose. They refuse any runs directory inside `data_paths`, so individual-level data never reaches them by design.
- **Skills and errors.** When an engine command exits non-zero, the skill shows the message to the user and stops. It never works around the error by writing the note by hand. The single exception is a `validate` failure, which the skill fixes.

## 7. Testing

**Unit tests** (offline, in the normal `pytest` run, synthetic data only):

| File | Covers |
| --- | --- |
| `test_trackers_local.py` | Flattening; metric filtering (bool, NaN and non-numeric dropped); status precedence; missing and invalid files; invalid run IDs not echoed; `runs_dir` resolution (absolute, relative to `code_repo`, relative to the vault); refusal inside `data_paths`, including via a symlink; `search` filters and ordering; `run_url`; `get_adapter` messages for every backend |
| `test_experiments.py` | Common config, `added`/`removed`/`changed`/`varied`, `hash_ignore`, md and json rendering, the no-difference line; `exp record` statuses (done, running, failed), the protocol gate writes nothing, protocol disagreement, unknown protocol, metrics split inference and stamps, the code fallback chain, `--into` on planned and running notes and its refusal on a done note, `--title` with `--into` rejected. Every written note passes `validate`. |
| `test_codeinfo.py` | Clean, dirty (tracked and untracked), not a repo, unset repo |
| `test_brief.py` | Both forms within their line limits on a vault with many notes; counts; "none" placeholders; the version warning line; exit 0 with lint errors |
| `test_new_flags.py` | `--summary`, `--body`, `--tag`, `--status` (valid and invalid), `--summary` with a human author |
| `test_plugin_manifest.py` | Both JSON files parse; plugin name equal in both; the marketplace entry has `source: "./"` and no `version`; `plugin.json` version equals `pyproject` and `__version__`; each `skills/*/SKILL.md` has YAML frontmatter with `name` equal to its directory and a non-empty `description`; `brain-core` is 80 lines or fewer; every `labbrain <subcommand>` token in a skill body is a real CLI subcommand (checked against the argparse parser); every skill that writes `ENGINE` has the matching `allowed-tools` rule; the ENGINE string appears byte-for-byte as in section 3 |

- **Fixtures.** `tests/fixtures/runs/` holds synthetic runs: a parent pair, a child pair that differs in `optim.lr` and adds `model.dropout`, a failed run, a run without `metrics.json`, and a run without a protocol.
- **Coverage.** At least 85% on `trackers/local.py` and `experiments.py`, within the existing `--cov-fail-under=85`.

**Smoke tests** (`tests/smoke/`, marker `smoke`):

- **When they run.** They are excluded from the default run by `addopts = -m "not smoke"`, and also skipped unless both `ANTHROPIC_API_KEY` and a `claude` executable are present.
- **Setup.** Each test copies `tests/fixtures/valid` into a temporary directory, runs `git init` and commits, and adds a `runs/` directory with synthetic runs. It writes `tracker.runs_dir: runs` with no `code_repo`.
- **Invocation:**

  ```
  claude --bare -p "/lab-brain:<skill> <args>" --plugin-dir <repo> \
    --permission-mode dontAsk --allowedTools "Read Edit Write" \
    --output-format json --max-turns 15 --max-budget-usd 1
  ```

  This runs with `cwd` at the temporary vault. The engine call must pass through the skill's own `allowed-tools` rule, which is part of what is being tested.
- **Cases:**
  1. `/lab-brain:idea Try cosine warmup on the small model` → exactly one new file in `ideas/inbox/`; it passes `validate`; `lint` reports 0 errors.
  2. `/lab-brain:exp-log run-c1 run-c2 --parent <fixture EXP>` on runs whose config carries `eval.protocol` and whose notes state a hypothesis → exactly one new experiment that passes `validate`, with `status: done`. Its `## Setup` contains every row of `tracker diff run-c1 run-c2 --parent <EXP>`. Each metric has `run_id` and `as_of`.
  3. `/lab-brain:exp-log run-noproto` → no new experiment with `status: done`, and the final output mentions "protocol".
- **Bare-mode check.** If `--bare` turns out not to expand `--plugin-dir` skills (the docs do not say), the harness falls back to running without `--bare`, with `CLAUDE_CONFIG_DIR` set to a temporary directory and `ANTHROPIC_API_KEY`. The plan's first smoke task verifies this and records the outcome in the smoke-test ADR.

**CI.**

- `ci.yml` gains a `plugin-validate` job: `actions/setup-node`, `npm install -g @anthropic-ai/claude-code`, `claude plugin validate . --strict`. It needs no API key.
- `smoke.yml` is `workflow_dispatch` only. It runs `uv run pytest -m smoke` when the `ANTHROPIC_API_KEY` secret exists, and otherwise exits with a notice.

## 8. M4 gate

`scripts/m4-gate.sh` checks the parent spec's gate: install from a local marketplace path, in a fresh Claude Code session.

1. Require `ANTHROPIC_API_KEY` and `claude`. Otherwise print the manual checklist below and exit 3.
2. `export CLAUDE_CONFIG_DIR=$(mktemp -d)`, so the user's own setup is never touched.
3. `claude plugin marketplace add <repo>`, then `claude plugin install lab-brain@lab-brain`.
4. Copy `tests/fixtures/valid` to a temporary vault.
5. In it, run `claude -p "/lab-brain:brief" --output-format stream-json --verbose`.
6. Assert that the `system/init` event lists plugin `lab-brain` and has an empty `plugin_errors`, and that the result text contains `Open ideas`.
7. Clean up both temporary directories and exit 0.

**Manual checklist** (no API key; about 2 minutes):

1. `/plugin marketplace add <repo path>`.
2. `/plugin install lab-brain@lab-brain`.
3. Restart Claude Code in a vault.
4. Check that `/lab-brain:brief` prints the brief.
5. Check that `/lab-brain:idea test idea` creates one note.
6. `/plugin marketplace remove lab-brain`, and delete the test note.

M4 is done when the unit tests and `plugin-validate` pass in CI, the smoke tests pass locally (or in the manual workflow), and the gate script or the manual checklist passes.

## 9. Engine release v0.2.0

- **Version.** `pyproject.toml`, `labbrain/__init__.py` and `plugin.json` go to `0.2.0`, with a `## 0.2.0 (YYYY-MM-DD)` entry in CHANGELOG dated on release day.
- **README.** Gains a "Using the plugin" section: install, the six skills, and the API-key note for smoke tests.
- **ADRs** in `docs/decisions/`, each named with the date it is written (`ADR-YYYYMMDD-<slug>`, written below as `<date>`):
  - `ADR-<date>-plugin-layout-and-engine-invocation`;
  - `ADR-<date>-local-tracker-adapter`, covering file layout, `runs_dir` resolution and the data-path refusal;
  - `ADR-<date>-exp-record-semantics`, covering the status rule, the protocol gate, `--into` and the split inference;
  - `ADR-<date>-skill-smoke-tests`, covering the harness and the outcome of the bare-mode check.
- **Delivery.** One PR from `feat/m4-plugin` into `main`. Merge on green CI and tag `v0.2.0`; each step needs the user's explicit approval.

## 10. Template v0.2.0 follow-up (`jorgebotas/lab-brain-template`)

This starts after the engine `v0.2.0` tag exists. It is a separate small PR, merged and tagged `v0.2.0` with the user's approval.

1. **Engine pin.** The hidden `engine_version` goes to `0.2.0`, so `labbrain_cmd` pins `@v0.2.0` and `engine_min_version` renders `0.2.0`.
2. **Plugin offer.** The generated `.claude/settings.json` adds:

   ```json
   "extraKnownMarketplaces": {
     "lab-brain": { "source": { "source": "github", "repo": "jorgebotas/lab-brain", "ref": "v0.2.0" } }
   },
   "enabledPlugins": { "lab-brain@lab-brain": true }
   ```

   Trusting the folder then offers to install the marketplace and plugin.
3. **Read-only allowlist.** It gains `tracker fetch`, `brief` and `code sha`.
4. **`CLAUDE.md`.** Gains a short "Skills" section listing `/lab-brain:idea`, `/lab-brain:exp-log`, `/lab-brain:decide`, `/lab-brain:handoff` and `/lab-brain:brief`. It also states that the skills come from the lab-brain plugin.
5. **The four v0.1.1 backlog items** (from the KB note `projects/lab-brain/template-review-backlog.md`):
   - document the allowlist entry format in the vault README;
   - scope the "run from the code repo root" sentence in CLAUDE.md;
   - parametrise `test_update` by the previous tag (`v0.1.0`);
   - document that, for subfolder vaults, `copier update` runs from inside the vault.
6. **Tests.** Settings tests assert the two new keys and the allowlist entries. Docs tests assert the Skills section. The render matrix still lints clean against engine v0.2.0, and `test_update` updates from `v0.1.0` to HEAD.

## 11. Deferred

- **To later milestones:**
  - `--sweep` and `tracker search` CLI (M7);
  - `wandb`/`mlflow` adapters (M7);
  - hooks, including SessionStart calling `brief --short` (M5);
  - the remaining skills (M6).
- **Not planned yet:**
  - claude.ai/Cowork-specific packaging;
  - publishing to a public marketplace directory.
