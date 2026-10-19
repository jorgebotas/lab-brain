# lab-brain plugin and capture skills (M4) — Design

Date: 2026-10-19 · Status: approved in brainstorming; revised after an independent review (section 12)
Parent spec: *lab-brain: ML Research Second Brain — Implementation Spec* (2026-10-13), sections 3, 7, 9, 11, 12 (M4).
Builds on: engine v0.1.0 (`docs/superpowers/specs/2026-10-15-labbrain-core-design.md`) and template v0.1.0 (`jorgebotas/lab-brain-template`).

## 1. Scope and decisions

**In scope:**

- The Claude Code plugin served from this repo: `plugin.json`, a single-plugin `marketplace.json`, and six skills: `brain-core`, `idea`, `exp-log`, `decide`, `handoff`, `brief`.
- The engine commands those skills need:
  - `tracker fetch`, `tracker diff`, `exp record`, `code sha`, `brief`, `finish`;
  - new flags on `new`;
  - exclusive note creation.
- The tracker adapter protocol plus the `local` adapter.
- Unit tests, a manifest test, opt-in headless smoke tests, an M4 gate script, CI changes and ADRs.
- Release as engine v0.2.0, then a follow-up template v0.2.0 (section 10).

**Out of scope.** These are listed with reasons in section 11:

- hooks;
- `/exp-log --sweep`;
- the `none`/manual tracker flow;
- `wandb`/`mlflow`;
- `TrackerAdapter.search`;
- the other M6 skills;
- `bin/` and `commands/`.

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
- Plugin skills live in `skills/<name>/SKILL.md` and are invoked as `/<plugin>:<skill>`.
- `${CLAUDE_PLUGIN_ROOT}` is substituted inline in SKILL.md bodies and in `allowed-tools` Bash rules. It is not an environment variable for Claude's Bash tool.
- **Bash permission rules:**
  - they match the whole command text;
  - they do not match past a variable assignment such as `p=$(…)`;
  - under `--permission-mode dontAsk`, an unapproved call is denied.
- Python dependencies are not installed automatically. uvx installs them, from PyPI, on the first call.
- `uvx --from <dir>` caches the build. A rebuild after source edits needs `[tool.uv] cache-keys`.
- If `version` is set in `plugin.json`, users update only when it is bumped. `claude plugin validate` (v2.1.289+) checks both manifests and the skills.
- `claude -p "/plugin:skill args"` expands the skill.
- `--bare` skips user plugins, settings, CLAUDE.md and memory, sends no skill listing, and needs `ANTHROPIC_API_KEY`. Its documented way to load a plugin is `--plugin-dir`.
- The stream-json `system/init` event lists `plugins`. It omits `plugin_errors` when there are none.

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
    experiments.py         # new: config_diff(), render_setup(), render_results(), record()
    brief.py               # new: build_brief(vault, findings, short) -> str
    codeinfo.py            # new: code_sha(repo, exclude) -> CodeInfo
    finish.py              # new: finish(paths, root, log_text, author) -> (findings, ok)
    notes.py               # changed: atomic_create (exclusive)
    scaffold.py            # changed: summary/body/tags/status; exclusive create with retry
    vault.py               # changed: Config.dataset_key
    cli.py                 # changed: new subcommands and flags
  scripts/
    m4-gate.sh             # new
  tests/
    fixtures/runs/         # new: synthetic local runs
    test_trackers_local.py
    test_experiments.py
    test_codeinfo.py
    test_brief.py
    test_finish.py
    test_new_flags.py
    test_plugin_manifest.py
    smoke/
      conftest.py          # skip unless ANTHROPIC_API_KEY and `claude` exist
      test_smoke_skills.py
  .github/workflows/
    ci.yml                 # changed: plugin-validate job
    smoke.yml              # new: workflow_dispatch only
  docs/decisions/          # four new ADRs (section 9)
  pyproject.toml           # changed: version, uv cache-keys, coverage include, smoke marker
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

**Version, licence and author.**

- `version` appears only in `plugin.json`. The manifest test keeps it equal to `pyproject.toml` and `labbrain.__version__`.
- `license` and `author` match `pyproject.toml`.
- If `claude plugin validate` rejects `"./"`, use `"."`, the other documented root form.

**Install.**

1. `/plugin marketplace add jorgebotas/lab-brain`. Append `@v0.2.0` to pin a tag.
2. `/plugin install lab-brain@lab-brain`.
3. Update with `claude plugin update lab-brain@lab-brain`, or by turning on auto-update for the marketplace.

**Engine command.**

- Every skill body writes the engine as the exact string `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain`. This document calls it `ENGINE`.
- Every skill's `allowed-tools` holds two rules: `Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)` and the same rule without the quotes. Permission matching is textual, so either spelling Claude types is covered.
- **Command rules for skills:**
  - a skill never assigns shell variables;
  - it never chains through `$(…)`;
  - it passes user-derived text only inside single quotes, writing a literal `'` as `'\''`.
- Engine commands print absolute paths. Skills pass those paths back verbatim.
- The engine finds the vault as it does today: `--vault`, then `LABBRAIN_VAULT`, then the nearest ancestor holding `.labbrain/config.yaml`.
- A vault's own `CLAUDE.md` keeps its pinned uvx command for humans and pre-commit. Both copies of the engine warn through `engine_min_version` when they are too old.
- **uv cache.** `pyproject.toml` gains `[tool.uv] cache-keys = [{ file = "pyproject.toml" }, { file = "labbrain/**/*.py" }]`, so that `uvx --from <checkout>` rebuilds after source edits. The plan verifies that uvx honours it. If it does not, the smoke harness and gate set `UV_NO_CACHE=1`.

## 4. Engine additions

### 4.0 Conventions

- **Exit codes** keep v0.1.0's convention:
  - 0: success;
  - 1: findings only (`validate`/`finish` errors, lint);
  - 2: every other failure, including tracker errors, missing notes, refused records and usage errors.
- **Messages.** New errors become `UsageError`s, or a new `TrackerError` that `main` handles the same way. Each message is printed as `labbrain: <message>` on stderr.
- **What messages may contain:**
  - note IDs only through `findings.display_id`, and run IDs only through `findings.sanitize`;
  - statuses only through the frozen-rules `_status_label` pattern;
  - never file contents, config values or frontmatter values.
- Titles printed by `brief` go through `findings.strip_controls`, as `list` does.

### 4.1 Tracker protocol (`labbrain/trackers/base.py`)

`RunRecord` is the `TypedDict` from parent spec section 9, with these fields:

- `run_id`, `name`, `url`
- `status` (`running | finished | failed | unknown`)
- `started_at`, `ended_at`
- `config`, flattened with dot keys
- `summary` (`dict[str, float]`)
- `tags`, `git_sha`, `git_dirty`, `notes`

`TrackerAdapter` is a `Protocol` with `name`, `fetch(run_ids) -> list[RunRecord]` and `run_url(run_id) -> str | None`. Parent spec's `search` is added in M7, with its first real user. `TrackerError(Exception)` carries a message that is safe to print.

`get_adapter(config, root)` maps `tracker.backend` to an adapter:

| Backend | Result |
| --- | --- |
| `local` | `LocalAdapter` |
| `wandb`, `mlflow` | `TrackerError("tracker backend '<name>' arrives in a later engine version")` |
| `none` | `TrackerError("tracker backend 'none' is not supported by exp record yet")` |
| anything else | `TrackerError("unknown tracker backend")` |

### 4.2 Local adapter (`labbrain/trackers/local.py`)

**Runs directory.**

- An absolute `tracker.runs_dir` is used as is, after expanding `~`.
- A relative one resolves against `code_repo` when `code_repo` is set, otherwise against the vault root. A relative `code_repo` itself resolves against the vault root.

**Protected paths.**

- Relative `data_paths` entries resolve against the vault root, matching the template's deny rules. Every entry is canonicalised (`~`, `..`, symlinks).
- The adapter canonicalises the runs directory, each `<runs_dir>/<run_id>` directory and each file it opens. If any of them lies inside, or equals, a canonical data path, it raises `TrackerError("run path is inside a protected data path")`.

**Run IDs.** An ID must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`. Anything else raises `TrackerError("invalid run id")`, and the ID is not echoed.

**Files per run:**

| File | Required | Use |
| --- | --- | --- |
| `config.yaml` | yes | YAML mapping, flattened with `confighash.flatten`. |
| `metrics.json` | no | JSON object, flattened. Keeps only `int` and `float` values that are not `bool` and are finite, as floats. |
| `meta.json` | no | Optional keys: `name`, `status`, `started_at`, `ended_at` (ISO 8601), `tags`, `git_sha`, `git_dirty`, `notes`, `url`. Unknown keys and badly typed values are ignored. `git_sha` is lowercased and kept only if it matches `^[0-9a-f]{7,40}$`. |

**Status.** A valid `meta.json` `status` wins. Otherwise a run is `finished` if `metrics.json` exists, and `unknown` if not.

**Errors.** Messages carry the run ID only when it passed validation. They pass through `findings.sanitize`, which redacts identifier-like tokens; `display_id` would blank every run ID, because run IDs are not note IDs:

- `run <id>: config.yaml not found`;
- `run <id>: <file> is not valid <YAML|JSON>`;
- `run <id>: config.yaml is not a mapping`.

**`run_url`.** Returns `meta.json`'s `url`, or `None`.

### 4.3 `labbrain tracker fetch RUN...`

- Prints a JSON array with one object per requested run, in request order.
- Each object is the `RunRecord`, with datetimes as ISO strings, plus four derived keys:
  - `config_hash`: `confighash.config_hash(config, hash_ignore)`, in the form `sha256:<hex>`.
  - `protocol`: `config[protocol_key]` as a string, or `null`.
  - `dataset`: `config[dataset_key]` as a string, or `null`. `dataset_key` is a new `Config` field, default `data.dataset`.
  - `headline`: the `summary` items whose names match any `headline_metrics` pattern (`fnmatch.fnmatchcase`), or all of `summary` when `headline_metrics` is empty.

### 4.4 `labbrain tracker diff RUN... --parent EXP-ID`

Steps:

1. The parent must be an experiment note with a non-empty `tracker.run_ids`. If not, exit 2 with `no experiment with ID <id>` or `parent <id> has no run ids`.
2. Fetch the parent's runs and the given runs through the configured adapter.
3. Drop keys matching `hash_ignore`.
4. Within each group, a key is **varied** if it is missing from some runs or differs between them. The rest form the group's **common config**.
5. Compare the common configs, skipping any key that is varied in either group:
   - `added`: keys only in the child;
   - `removed`: keys only in the parent;
   - `changed`: keys in both with different values.
6. `varied_here` lists the child group's varied keys, and `varied_parent` lists the parent group's.

Output is markdown only, the Setup block:

```
Config diff against [[EXP-...]] (hash_ignore keys omitted):

| key | parent | this |
| --- | --- | --- |
| optim.lr | 0.001 | 0.0003 |
| model.dropout | — | 0.1 |

Varied across these runs: data.fold.
Varied across the parent's runs: seed_group.
```

**Rendering rules:**

- Values are compact `json.dumps`, with `|` escaped as `\|`.
- `—` marks an absent key.
- Rows are sorted by key.
- With no differences, the table is replaced by `Same config as [[EXP-...]] (hash_ignore keys omitted).`
- Each `Varied` line is omitted when its list is empty.

`experiments.config_diff()` returns a `ConfigDiff` dataclass, which unit tests assert on directly.

### 4.5 `labbrain exp record RUN... --author A (--title T | --into EXP-ID) [options]`

**Options:** `--parent EXP-ID`, `--protocol EVAL-ID`, `--dataset DS-ID`, `--hypothesis TEXT`, `--summary TEXT`, `--link ID` (repeatable), `--at`.

- `--title` and `--into` form an argparse mutually exclusive group, and one of them is required (exit 2).
- The command creates an experiment note from runs, or fills in a planned or running one. It writes atomically and prints the note's absolute path.

**Checks before writing.** Any failure exits 2 and writes nothing:

- `--parent` and every `--link` must name an existing note (`no note with ID <id>`).
- **Protocol:** `--protocol`, or else the shared `protocol` of the runs that carry one. Runs without the key are ignored. If two runs carry different values, the command stops with `runs disagree on protocol; pass --protocol`. The chosen ID must be a protocol note (`protocol not found`); the value is not echoed when it came from a run config.
- **Dataset:** `--dataset`, or else the shared run `dataset`, with the same disagreement rule. The chosen ID must be a dataset note (`dataset not found`).
- **Status** comes from the runs:
  - any run `failed` → `failed`;
  - else any `running` or `unknown` → `running`;
  - else (all `finished`) → `done`.
- **`done` gate:** a `done` result needs both a protocol and a dataset. The schema requires `dataset` for `done`, and parent spec section 7 requires a protocol. Otherwise exit 2 with `protocol and dataset required to record finished runs: pass --protocol/--dataset or set <protocol_key>/<dataset_key> in the run config`, naming only the missing ones.

**Frontmatter:**

| Field | Value |
| --- | --- |
| `tracker` | `{backend: <config backend>, run_ids: [RUN...], url: <first non-null run_url or null>}` |
| `config_hash` | The shared hash when every run has the same `config_hash`; otherwise `null` (Setup lists the varied keys) |
| `protocol`, `dataset` | As resolved above (may be `null` for running or failed) |
| `code` | `repo`: `code_repo` or `null`. `sha`: the runs' shared valid `git_sha`. If no run has one and `code_repo` is a git repo, the `code sha` result is used. If runs disagree, it is `null`. `dirty`: `true` if any run reports dirty, or if `code sha` was used and is dirty; otherwise `false` when a SHA is known. `code` is `null` when no SHA is known. |
| `metrics` | One entry per run per headline metric, in run order then name order: `{name, value, split, run_id, as_of: today}`. `split` is the first `/`- or `.`-separated segment of the name when that segment is one of `train`, `val`, `valid`, `validation`, `test`; otherwise `null`. `name` is kept as given. |
| `status` | As resolved above |
| `hypothesis` | `--hypothesis`, if given |
| `links` | Existing links, then `--parent`, then each `--link`, deduplicated |
| `updated` | Today (`LABBRAIN_NOW`/`--at` honoured) |

**Body.** A new note is built from the `new experiment` skeleton:

- the For-future-agents block uses `--summary`, collapsed to one line, or keeps the placeholder;
- `## Hypothesis` gets `--hypothesis`;
- `## Setup` gets the `tracker diff` block with `--parent`; otherwise `Runs: run-a, run-b.` plus a `Varied across these runs:` line when needed;
- `## Results` gets `| metric | value | split | run |`, with one row per metric entry and `|` escaped;
- `## Interpretation` and `## Next` stay empty.

**`--into`.**

- The target must be an experiment whose status is `planned` or `running`. Otherwise exit 2 with `<id> is <status label>; only planned or running experiments can be filled in`.
- `tracker`, `config_hash`, `protocol`, `dataset`, `code`, `metrics`, `status` and `updated` are set as in the table, replacing what the note held. A planned note's own `protocol`/`dataset` count as the fallback before the run values.
- `links` keeps existing entries and adds new ones.
- `title`, `created`, `author`, `tags` and an existing `hypothesis` are kept; `--hypothesis` replaces the hypothesis.
- The Setup and Results blocks are appended at the end of their sections. No other body text changes.

### 4.6 `labbrain code sha [--repo PATH]`

- Prints `{"repo": "<as given or configured>", "sha": "<40 hex>", "dirty": true|false}`.
- The default repo is `code_repo`, resolved against the vault root.
- `dirty` means `git status --porcelain` is non-empty; untracked files count.
- When the vault lies inside that repo, the vault's own directory is excluded with the pathspec `:(exclude)<vault prefix>`. A note just written therefore never makes the code look dirty.
- Exit 2 with `code repo not set` or `not a git repository`. Uses `gitutil`.

### 4.7 `labbrain finish PATH... --log TEXT [--author A]`

This is the single end step of every writing skill.

1. Run `validate` on the paths (schema, required sections, PHI when protected).
2. If there are error findings, print them like `validate`, exit 1 and stop.
3. Otherwise run `sync` (apply), then regenerate the index, then append `TEXT` to today's log with `--author`.
4. Print the sync changes and `index.md updated` or `already up to date`, then exit 0.

A sync conflict prints as a finding and exits 1, after the index and log steps.

`new` and `exp record` take `--finish TEXT`, which runs this same step on the written path in the same process. That lets `/idea` finish in one Bash call.

### 4.8 `labbrain brief [--short]`

- Loads the vault without the stderr version warning; the warning appears once, inside the output.
- Runs lint with the default base.
- Prints note IDs and titles only (`strip_controls` applied), never body text.
- "Stale claims" means claims whose `status` is `stale`.
- Lists are newest ID first.

**Full form**, at most 40 lines:

```
<project_name> · engine <version>
<version warning line, if any>

Recent handoffs:
  HO-20261019-1420-claude  <title>
  (up to 3; "  none" if empty)

Experiments running (N):
  EXP-...  <title>
  (up to 5; "  … and K more" beyond; "  none" if empty)
Experiments planned (N):
  (same shape)
Stale claims (N):
  (same shape)

Open ideas: N · Lint: E errors, W warnings
```

**`--short`**, at most 4 lines; the M5 SessionStart hook will call it:

```
<project_name> · engine <version>
<version warning line, if any>
Last handoff: HO-...  <title>            (or "Last handoff: none")
Running N · Planned N · Stale claims N · Open ideas N · Lint errors E
```

Exits 0 even when lint has errors; it only reports them.

### 4.9 Changes to `labbrain new`

| Flag | Effect |
| --- | --- |
| `--summary TEXT` | Collapsed to one line. Replaces the For-future-agents placeholder for agent authors; exit 2 if it reads as a heading (`notes.HEADING_RE`). For human authors it is ignored, with a stderr note. |
| `--body TEXT` | Placed under its own `## Notes` heading, after the For-future-agents block and before the required section headings, so it never counts as part of that block. Control characters are stripped. Exit 2 if any line is a level-2 heading (`notes.H2_RE`). |
| `--tag TAG` (repeatable) | Fills `tags`, deduplicated, in order given. |
| `--status STATUS` | Only statuses whose skeleton validates: experiment `planned`/`running`, decision `proposed`/`accepted`, otherwise the type's default. Exit 2 (`UsageError`) for anything else. |
| `--finish TEXT` | See 4.7. |

**Exclusive creation.**

- `notes.atomic_create(path, text)` writes a temp file and links it into place with `os.link`, which fails if the target exists, then removes the temp file.
- `scaffold.create` (and `exp record`) retry ID minting up to 5 times on `FileExistsError`. New-ID minting already avoids existing files, so the retry picks the next free ID.
- This stops two handoffs minted in the same minute (for example by parallel subagents) from overwriting each other.
- On filesystems without hard links (`EPERM`, `ENOTSUP`, `EXDEV`, `EMLINK`, `ENOSYS`), `atomic_create` falls back to an exclusive `open(O_CREAT | O_EXCL)`, which still never replaces a file.

## 5. Skills

**Shared rules.**

- **Frontmatter:** each skill has `name` (equal to its directory), `description`, `argument-hint` where it takes arguments, and the two ENGINE `allowed-tools` rules. No skill sets `disable-model-invocation`.
- **Narrow descriptions:** every skill except `brain-core` has one. They say "Use only when the user explicitly asks to …", except that `handoff` and `brief` also name the situations where Claude may invoke them itself.
- **Body:** a numbered procedure, the exact ENGINE commands, and a "Do not" list.
- **Author:** agent-written notes use `--author claude`. Handoffs use `--agent claude`, or a subagent's own agent name.
- **Commands:** every command follows section 3's rules: no variable assignment, no `$(…)`, user text single-quoted, absolute paths passed back verbatim.
- **Finishing a write:** every writing skill ends with `--finish '<skill>: <one-line summary>'`, or with `ENGINE finish <abs path> --log '<skill>: …' --author claude` after Edit-tool changes. On exit 1 the skill fixes the reported fields and runs `finish` again. A skill never ends with a note that fails validation.
- **On engine errors:** for any other non-zero exit, the skill shows the message and stops. It never writes the note by hand instead.
- **Shared "Do not" list:**
  - never edit `index.md`, anything under `raw/`, or a frozen note;
  - never invent IDs, hypotheses, protocols, datasets or metric values;
  - never paste text that `phi-scan` matched;
  - never write outside the vault.

| Skill | Description trigger | Procedure |
| --- | --- | --- |
| `brain-core` | Any session whose working directory is inside a lab-brain vault, or when the user talks about the vault's experiments, ideas, decisions, protocols or handoffs | At most 80 lines including frontmatter, writes nothing. Covers: find the vault with `ENGINE vault root`; read `ENGINE config` for `protected_data` and `search`; a compressed write-rules table; IDs come only from `new`/`new-id`/`exp record`; the freshness rule (copied numbers carry a run ID or as-of date); PHI rules when protected; read `index.md` before searching; use qmd only when `search: qmd`; one line per other skill. |
| `idea` | User explicitly asks to capture or jot down an idea | Asks no questions and makes one Bash call: `ENGINE new idea --title '<first sentence, ≤80 chars>' --author claude --summary '<first sentence>' --body '<full text>' [--tag '<t>']... --finish 'idea: <title>'`. Tags only from words already in the text. |
| `exp-log` | User explicitly asks to log runs or an experiment | 1. `ENGINE tracker fetch RUN...`. 2. Hypothesis: from run tags or notes when one is stated there; otherwise ask, and never invent it. 3. Protocol and dataset: the fetched values; otherwise ask, offering `ENGINE list --type protocol` / `--type dataset`, and never invent them. If no dataset note fits, say so and suggest creating one with `ENGINE new dataset`. 4. `ENGINE exp record RUN... --author claude --title '…' --summary '…' --hypothesis '…' [--parent EXP] [--protocol P] [--dataset D] --finish 'exp-log: …'`. If the user names a planned note, use `--into <ID>` instead of `--title`. 5. Write `## Interpretation` (Edit tool) only if the user asked, starting with `(agent interpretation, unreviewed)`, then `ENGINE finish`. **`--planned`:** ask for the hypothesis; `ENGINE new experiment --title '…' --author claude --summary '…'`; with Edit, set `hypothesis` and fill `## Hypothesis` and the planned `## Setup`; then `ENGINE finish`. A later `/lab-brain:exp-log RUN --into <ID>` fills it in. |
| `decide` | User explicitly asks to record a decision or ADR | 1. Draft Context, Decision and Consequences from the conversation. 2. If no alternatives were discussed, ask for them. 3. `ENGINE new decision --title '…' --author claude --summary '…' --status accepted`, or `--status proposed` when the user calls it a proposal. 4. Fill in the four sections with Edit. 5. If it reverses an earlier ADR (the user names it, or pick from `ENGINE list --type decision`), set `supersedes: <ADR-ID>`. `finish` runs `sync`, which marks the old ADR; never edit it by hand. 6. `ENGINE finish`. |
| `handoff` | User asks for a handoff, a session is ending, work passes to another agent, or a subagent is finishing delegated vault work | 1. `git status --short` and `git diff --stat` in the vault. If `code_repo` is set and exists, also `git -C <code_repo> status --short` and `git -C <code_repo> diff --stat`. These are read-only git commands, which Claude Code auto-allows. 2. `ENGINE new handoff --title '…' --author claude --agent <claude or own agent name> --summary '…'`. 3. With Edit, set `session_goal` and `files_touched`, and fill in Done, In progress, Blockers and "Next step for whoever picks this up", linking note IDs. 4. `ENGINE finish`. |
| `brief` | User asks "where are we", for a status or briefing, or a session starts in a vault | Run `ENGINE brief` and show its output verbatim. Writes nothing. |

## 6. Error handling and output safety

- Every new message follows 4.0. Unexpected exceptions go through `main`'s existing handler, which prints only the exception type.
- **Echoed values.** `tracker fetch` and the Setup and Results blocks deliberately carry run config and metric values; that is their purpose. Individual-level data stays out because every run path is checked against `data_paths` (4.2). Notes are still PHI-scanned by `finish` in protected vaults.
- **Skills and errors.** Skills stop on engine errors; they never work around them (section 5).

## 7. Testing

**Unit tests** (offline, in the normal `pytest` run, synthetic data only):

| File | Covers |
| --- | --- |
| `test_trackers_local.py` | Flattening; metric filtering (bool, NaN and non-numeric dropped); status precedence; `git_sha` validation; missing and invalid files; invalid run IDs not echoed; `runs_dir` resolution (absolute, relative to `code_repo`, relative to the vault); refusal when `runs_dir`, a run directory, or a symlinked run directory lies in `data_paths`; `run_url`; `get_adapter` messages for every backend |
| `test_experiments.py` | `ConfigDiff` added/removed/changed, varied keys in the child group and in the parent group kept out of added/removed, `hash_ignore`, markdown rendering with `|` escaping, the no-difference line. `exp record`: done/running/failed; the done gate for a missing protocol, a missing dataset and both, writing nothing in each case; protocol and dataset disagreement and not-found, with values not echoed; parent and link not found; split inference and stamps; the `code` fallback chain, including disagreeing SHAs → `null`; `--into` on planned and running notes, refused on done; `--title`/`--into` exclusivity. Every written note passes `validate`. |
| `test_codeinfo.py` | Clean, dirty (tracked and untracked), dirt only inside the vault prefix is ignored, not a repo, unset repo |
| `test_finish.py` | Clean path → sync, index and log happen; error findings → exit 1, with no index or log change; `--finish` on `new` and `exp record` |
| `test_brief.py` | Both forms within their line limits on a vault with many notes; counts; "none" placeholders; the version warning appears once; control characters in titles stripped; exit 0 with lint errors |
| `test_new_flags.py` | `--summary` (multi-line collapsed; human author note); `--body` (placement; `## ` rejected); `--tag`; `--status` (allowed values, refused ones exit 2); exclusive create, where a pre-existing target forces the next ID and never an overwrite |
| `test_plugin_manifest.py` | Both JSON files parse; plugin name equal in both; the marketplace entry has a root source and no `version`; `plugin.json` version, licence and author equal `pyproject`, and the version equals `__version__`; each `skills/*/SKILL.md` has YAML frontmatter with `name` equal to its directory and a non-empty `description`; no skill sets `disable-model-invocation`; `brain-core` is 80 lines or fewer; every `labbrain <subcommand>` token in a skill body is a real CLI subcommand (checked against `build_parser()`); every skill has both ENGINE `allowed-tools` rules; skill bodies contain no `$(` and no `p=`-style assignment before ENGINE |

**Existing tests and config to update:**

- `test_adrs.py` expects 12 ADRs instead of 8.
- `[tool.coverage.report] include` gains `*/labbrain/trackers/*` and `*/labbrain/experiments.py`.
- The `smoke` marker joins `markers`, and `addopts` gains `-m "not smoke"`.
- `test_meta`'s repo PHI scan covers `skills/`, `.claude-plugin/` and `scripts/`.

**Fixtures.** `tests/fixtures/runs/` holds synthetic runs:

- `run-001` and `run-002`, matching the valid fixture's experiments;
- `run-c1` and `run-c2`, children of `run-002` that change `optim.lr`, add `model.dropout`, differ in `data.fold`, and carry `eval.protocol: EVAL-v2` and `data.dataset: DS-20260801-main-split`;
- `run-failed`;
- `run-nometrics`;
- `run-noproto`, which is finished but has no protocol key.

**Smoke tests** (`tests/smoke/`, marker `smoke`):

- **When they run.** They are deselected by default, and also skipped unless both `ANTHROPIC_API_KEY` and a `claude` executable are present.
- **Setup.** Each test copies `tests/fixtures/valid` into a temporary directory, adds `runs/` from the fixtures, sets `code_repo: ''`, then runs `git init` and commits.
- **Invocation:**

  ```
  claude --bare -p "/lab-brain:<skill> <args>" --plugin-dir <repo> \
    --permission-mode dontAsk --allowedTools "Read Edit Write" \
    --output-format json --max-turns 15 --max-budget-usd 1
  ```

  This runs with `cwd` at the temporary vault and `UV_NO_CACHE=1` if the section 3 cache check failed.
- **Cases:**
  1. `/lab-brain:idea Don't forget cosine warmup on the small model`, which contains an apostrophe → exactly one new file in `ideas/inbox/`; its body contains `Don't forget`; it passes `validate`; `lint` reports 0 errors; today's log has an `idea:` line.
  2. `/lab-brain:exp-log run-c1 run-c2 --parent EXP-20260910-label-smoothing` → exactly one new experiment that passes `validate`, with `status: done`, `protocol: EVAL-v2` and the fixture dataset. Its `## Setup` contains every row of `tracker diff` for the same runs and parent. Every metric has `run_id` and `as_of`.
  3. `/lab-brain:exp-log run-noproto` → no new experiment with `status: done`, and the final output mentions "protocol".
- **First plan task for smoke.** Confirm that a skill's own `allowed-tools` rule is honoured under `dontAsk`. If it is not, the harness adds both ENGINE rules (with the repo path in place of the variable) to `--allowedTools`, and the smoke-test ADR records it.
- **Not covered.** Slash invocation only. Bare mode sends no skill listing, so automatic invocation of `brain-core` and `handoff` is outside the smoke tests; it is covered by the manual checklist in section 8.

**CI.**

- `ci.yml` gains a `plugin-validate` job: `actions/setup-node`, `npm install -g @anthropic-ai/claude-code`, print `claude --version`, fail if it is below 2.1.289, then `claude plugin validate . --strict`. It needs no API key.
- `smoke.yml` is `workflow_dispatch` only. It runs `uv run pytest -m smoke` when the `ANTHROPIC_API_KEY` secret exists, and otherwise exits 0 with a notice.

## 8. M4 gate

`scripts/m4-gate.sh` checks the parent spec's gate: install from a local marketplace path, in a fresh Claude Code session.

1. Require `ANTHROPIC_API_KEY` and `claude`. Otherwise print the manual checklist below and exit 3.
2. `export CLAUDE_CONFIG_DIR=$(mktemp -d)`, so the user's own setup is never touched.
3. `claude plugin marketplace add <repo>`, then `claude plugin install lab-brain@lab-brain`.
4. Copy `tests/fixtures/valid` to a temporary vault.
5. In it, run `claude -p "/lab-brain:brief" --permission-mode dontAsk --output-format stream-json --verbose`.
6. Assert that the `system/init` event lists plugin `lab-brain` and that `plugin_errors` is absent or empty (read it with a default of `[]`), and that the result text contains `Open ideas`.
7. Clean up both temporary directories and exit 0.

**Manual checklist** (no API key; about 3 minutes):

1. `/plugin marketplace add <repo path>`.
2. `/plugin install lab-brain@lab-brain`.
3. Restart Claude Code in a vault.
4. Check that `/lab-brain:brief` prints the brief.
5. Check that `/lab-brain:idea test idea` creates one note.
6. Ask "what's the state of this vault?" and check that Claude uses `brain-core` or `brief` unprompted.
7. Ask "write a handoff" and check that `handoff` runs.
8. `/plugin marketplace remove lab-brain`, and delete the test notes.

M4 is done when the unit tests and `plugin-validate` pass in CI, the smoke tests pass locally (or in the manual workflow), and the gate script or the manual checklist passes.

## 9. Engine release v0.2.0

- **Version.** `pyproject.toml`, `labbrain/__init__.py` and `plugin.json` go to `0.2.0`, with a `## 0.2.0 (YYYY-MM-DD)` entry in CHANGELOG dated on release day.
- **README.** Gains a "Using the plugin" section: install, the six skills, and the API-key note for smoke tests.
- **ADRs** in `docs/decisions/`, each a valid decision note named `ADR-YYYYMMDD-<slug>` with the date it is written:
  - `plugin-layout-and-engine-invocation`, covering the ENGINE string, both permission rules, the command rules for skills, and uv cache-keys;
  - `local-tracker-adapter`, covering the file layout, `runs_dir` resolution, per-path data-path refusal, and `dataset_key`;
  - `exp-record-and-finish`, covering the status rule, the done gate, `--into`, split inference, `code` fallback, `finish` and exclusive create;
  - `skill-smoke-tests`, covering the harness, the outcome of the `dontAsk` + `allowed-tools` check, and the uv cache outcome.
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

3. **Read-only allowlist.** It gains `tracker fetch`, `brief` and `code sha`.
4. **`CLAUDE.md`.** Gains a short "Skills" section listing `/lab-brain:idea`, `/lab-brain:exp-log`, `/lab-brain:decide`, `/lab-brain:handoff` and `/lab-brain:brief`, and saying they come from the lab-brain plugin.
5. **The four v0.1.1 backlog items** (from the KB note `projects/lab-brain/template-review-backlog.md`):
   - document the allowlist entry format in the vault README;
   - scope the "run from the code repo root" sentence in CLAUDE.md;
   - parametrise `test_update` by the previous tag (`v0.1.0`);
   - document that, for subfolder vaults, `copier update` runs from inside the vault.
6. **Tests.** Settings tests assert the two new keys and the allowlist entries. Docs tests assert the Skills section. The render matrix still lints clean against engine v0.2.0, and `test_update` updates from `v0.1.0` to HEAD.

## 11. Deferred

| Item | Why | When |
| --- | --- | --- |
| `--sweep` | The local adapter has no real sweep concept | M7, with W&B |
| `tracker.backend: none` (ask the user for values, record `backend: manual`) | Needs a manual-metrics input path; the template default is `local` | M7 |
| `wandb`, `mlflow` adapters; `TrackerAdapter.search` and a CLI for it | No user before M7 | M7 |
| Code SHA on `--planned` notes | `exp record --into` records the code when runs exist | M7, if wanted |
| Hooks, including SessionStart calling `brief --short` | Milestone order | M5 |
| Remaining skills | Milestone order | M6 |
| `bin/`, `commands/`, public marketplace listing | `bin/` blocks claude.ai/Cowork installs; `commands/` is the legacy format | Not planned |

## 12. Review changes (2026-10-19)

An independent review against the engine code and current docs changed the following:

- **`dataset` is now resolved and required for `done`.** It comes from `--dataset` or the new `dataset_key`, because the schema rejects done experiments without one.
- **The finish step moved into the engine** (`finish`, `--finish`). Skills no longer chain `p=$(…)`, which permission rules cannot approve. User text is single-quoted.
- **Absolute paths everywhere.** A relative path resolves against the cwd, which skips validation in subfolder vaults.
- **`tracker diff`** keeps varied keys out of added and removed, and reports the parent's varied keys separately. JSON output was dropped.
- **`code`:** disagreeing SHAs give `null` rather than HEAD. `meta.json` SHAs are validated, and the vault is excluded from the code repo's dirty check.
- **`exp record`** writes the For-future-agents summary, checks parent and link IDs, and runs `sync` through `finish`.
- **`new --status`** is restricted to statuses whose skeleton validates and uses exit 2. `--summary` is one line, and `--body` rejects H2 headings.
- **Conventions:** exit codes follow v0.1.0 (2 for every non-finding failure), and messages use `display_id` and status labels.
- **Data-path checks** cover each run directory and file, and relative `data_paths` resolve against the vault root.
- **Exclusive note creation** stops parallel handoffs from overwriting each other.
- **Smoke and gate details:** uv cache-keys for local-checkout rebuilds; a `dontAsk` + `allowed-tools` check; quoted and unquoted permission rules; `plugin_errors` may be absent; `--permission-mode dontAsk` in the gate.
- **CI:** minimum Claude Code version 2.1.289 in CI; existing test and config updates (ADR count, coverage include, markers, repo PHI scan).
- **Scope:** the `none` backend and `search()` moved to section 11, and the `--bare` fallback was dropped because `--plugin-dir` is the documented bare-mode loader.

## 13. Audit changes (2026-10-19)

An adversarial audit of PR #4 reproduced the bugs below. These behaviours now supersede the earlier sections where they differ:

- **Supersession waits for the successor.** `sync` ignores `supersedes:` on a decision that is still `proposed` or an experiment that is still `planned`. The old note is marked superseded once the successor is accepted or done and sync runs again.
- **Protected text is refused before writing.** When `protected_data` is true, `new` and `exp record` scan the text they would write (title, and with it the minted ID; summary, body, hypothesis) with the PHI scanner. A hit not covered by the allowlist writes nothing and exits 2 with `the note text matches a protected-data pattern (<rule>); rephrase it`. With `--into`, only the lines the command adds are checked.
- **Generated blocks are marked and replaced.** `exp record` wraps the Setup and Results blocks it generates in `<!-- labbrain:setup -->`/`<!-- labbrain:results -->` marker comments. A later `--into` replaces a marked block in place and appends only when no marked block exists. Re-filling a `running` experiment therefore leaves no stale results.
- **More refusals, all exit 2:**
  - a `--summary` or `--hypothesis` that is a heading or opens a code fence;
  - a `--body` with unbalanced fences;
  - duplicate run IDs;
  - run-file keys that collide when flattened;
  - run data nested more than 200 levels deep;
  - run files that cannot be encoded as UTF-8;
  - a `--into` target that is not valid UTF-8.
- **Robust parsing.** YAML constructor errors (for example an impossible date) count as invalid YAML everywhere, so notes, run files and config report findings instead of crashing. `config_hash` stays unchanged for ordinary configs and falls back to stringified keys when a key sort fails.
- **Output.** Table cells collapse control characters and newlines. Floats are written in a form YAML 1.1 reads back as a float (`1.0e-07`). Section matching uses the parser's own heading rule.
- **`code sha`** takes the vault prefix from git and excludes it as a literal pathspec.
- **Skills** write free-text options as `--option='value'`, so a value may start with `-`. They stop and ask for a rephrase on the protected-data refusal.
- **Smoke harness and gate** run with `UV_NO_CACHE=1`, because whether `[tool.uv] cache-keys` triggers a rebuild of a local checkout depends on the uv version.
