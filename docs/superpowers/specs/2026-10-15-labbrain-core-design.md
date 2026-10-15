# labbrain core (M1 + M2) — Design

Date: 2026-10-15 · Status: approved; amended after self-review (section 12)
Parent spec: *lab-brain: ML Research Second Brain — Implementation Spec* (2026-10-13), sections 5, 6, 10, 11, 12.

## 1. Scope

The parent spec is split into five sub-projects, each with its own spec → plan → build cycle:

| # | Sub-project | Parent milestones |
|---|---|---|
| **1** | **`labbrain` core (this document)** | **M1 + M2** |
| 2 | Copier template (`lab-brain-template`) | M3 |
| 3 | Plugin, skills, hooks | M4 + M5 |
| 4 | Claims, literature, tracker adapters, search | M6 + M7 |
| 5 | Docs and v1.0.0 | M8 |

**In scope:** the `labbrain` Python package and CLI in this repo: vault discovery, config, frontmatter schemas, ID generation, note scaffolding, validation, supersession sync, index, daily log, all lint rules, the PHI scanner with allowlist, fixtures, tests and CI.

**Out of scope:** `claims.py`, `trackers/`, `lit fetch`, `import`, `search`, `migrate`, skills, hooks, plugin manifests, the template. No directories are created for them here.

**Gates (from parent spec, made concrete in section 9):**
- M1: unit tests pass; `validate` and `index` work on the valid fixture.
- M2: every broken fixture triggers exactly its rule; the valid fixture yields zero findings; the scanner never echoes matches.

## 2. Repository layout

```
lab-brain/
  pyproject.toml            # uv-managed, hatchling build, Python >=3.11
                            # deps: pydantic>=2, pyyaml>=6 (reads), ruamel.yaml (writes)
                            # dev: pytest, pytest-cov, ruff
                            # script: labbrain = labbrain.cli:main
  labbrain/
    __init__.py             # __version__
    __main__.py             # python -m labbrain
    cli.py                  # argparse; parses, calls library, formats text/JSON. No logic.
    layout.py               # folder names, note types, skip lists (constants only)
    validate.py             # single-file validation used by `validate` and the M5 hook
    vault.py                # root discovery, Config model, Vault graph, atomic writes
    notes.py                # Note: path + frontmatter + body; split/join; wikilink extraction
    schema.py               # pydantic BaseNote + 9 subclasses, discriminated union on `type`
    ids.py                  # new_id(), slugify(), ID regexes, collision resolution
    scaffold.py             # skeleton notes for `labbrain new`
    sync.py                 # supersession propagation, protocol freezing
    query.py                # list/filter notes, inbound/outbound links
    confighash.py           # flatten config, apply hash_ignore, sha256
    index.py                # render index.md
    log.py                  # append to log/YYYY-MM-DD.md
    findings.py             # Finding + JSON serialization + message sanitizer
    gitutil.py              # thin subprocess wrapper: read files/trees at a ref
    phi.py                  # pattern + small-cell scanner, allowlist
    lint/
      __init__.py           # registry, run(vault, base, rules, today) -> list[Finding]
      rules/
        schema_rules.py     # schema, missing-section
        link_rules.py       # broken-link, orphan
        frozen_rules.py     # frozen-edit
        protocol_rules.py   # protocol-missing, cross-protocol, claim-stale, duplicate-config, sync-pending
        hygiene_rules.py    # concept-unsourced, inbox-age, dirty-code, undated-fact, index-stale
        phi_rules.py        # phi
  tests/
    conftest.py
    fixtures/valid/         # static valid vault
    fixtures/mutations.py   # one named mutation per lint rule
    test_*.py
  docs/decisions/           # engine ADRs, ADR-YYYYMMDD-<slug>.md, decision-note format
  .pre-commit-hooks.yaml    # lets vaults reference labbrain-lint / labbrain-phi-scan by repo URL
  .github/workflows/ci.yml
  CHANGELOG.md
  README.md                 # minimal until sub-project 5
```

Deviations from the parent tree (each gets an ADR): `lint.py` → `lint/` package; added `layout.py`, `validate.py`, `findings.py`, `scaffold.py`, `sync.py`, `query.py`, `confighash.py`, `gitutil.py`, `.pre-commit-hooks.yaml`.

### Module boundaries

- **`schema.py` knows nothing about config or the filesystem.** It validates shape, types and per-type status enums. Everything context-dependent (ID format against configured prefixes, `id` = filename, author membership, link resolution) is a lint rule or a `validate` check.
- **`cli.py` imports heavy modules lazily inside each command.** M5 hooks invoke `labbrain` on every tool call; startup cost matters. argparse (stdlib) instead of typer for the same reason.
- **`gitutil.py` shells out to `git`**; no GitPython dependency.
- **One `Finding` type** is emitted by lint, `validate` and `phi-scan`. The `phi` lint rule is phi-scan output filtered by the allowlist.

## 3. Vault, config, notes

### Discovery

`--vault PATH` if given; else `LABBRAIN_VAULT` if set; otherwise the nearest ancestor of cwd containing `.labbrain/config.yaml`. Neither → exit 2 with a message naming both mechanisms.

### Config (`.labbrain/config.yaml`)

A pydantic model with `extra="allow"` (a newer template may add keys an older engine does not know). All fields consumed by later sub-projects are defined now with defaults so the template can render a complete file once:

```yaml
project_name: str
project_slug: str
owner: str
lab_members: []                  # empty = any human author accepted
agents: [claude, codex, gemini]  # authors treated as agents
modality: str
tracker: {backend: local, project: <slug>, runs_dir: runs}
protected_data: true
data_paths: []
min_cell_size: 11
code_repo: ""
vault_location: standalone
target_venues: []
engine_min_version: "0.1.0"
id_prefixes: {experiment: EXP, protocol: EVAL, claim: CLM, idea: IDEA,
              decision: ADR, literature: LIT, handoff: HO, dataset: DS}
inbox_max_days: 30
headline_metrics: []
hash_ignore: [seed, "*.seed", output_dir, "*.output_dir", timestamp, run_name]
protocol_key: eval.protocol
search: none
phi: {mrn_regex: null, denylist_file: .labbrain/phi-denylist.txt}
```

`project_slug` is not embedded in IDs; `id_prefixes` only allows renaming the type prefixes. If the installed engine is older than `engine_min_version`, every command prints one warning to stderr and continues.

### What counts as a note

A note is a `.md` file with YAML frontmatter containing a `type` key, under a note folder: `experiments/ protocols/ claims/ ideas/ concepts/ decisions/ literature/ handoffs/ datasets/`. Skipped entirely: `raw/`, `scratch/`, `manuscripts/`, `templates/`, `log/`, `.labbrain/`, `.git/`, `index.md`, `CLAUDE.md`, `AGENTS.md`, and every `README.md`. A `.md` file inside a note folder (other than `README.md`) **without** frontmatter is a `schema` error, so stray files are never silently ignored.

### Vault graph

Notes are keyed by **filename stem**, not by the `id` field, so a note whose `id` disagrees with its filename fires only `schema` and its inbound links still resolve. Two files with the same stem in different folders are kept as a list under that key and reported by `schema` as a duplicate ID.

One parse pass builds:
- `notes: dict[id, Note]`, `by_type: dict[type, list[Note]]`
- `outbound: dict[id, set[id]]` and `inbound: dict[id, set[id]]`
- `parse_errors: list[Finding]` (a bad note never aborts the load)

Links are harvested from body wikilinks (`[[ID]]`, `[[ID|text]]`, `[[ID\|text]]`, `[[ID#heading]]`, `[[ID^block]]`), ignoring fenced code blocks and inline code, and from every ID-bearing frontmatter field: `links`, `evidence`, `sources`, `protocol`, `dataset`, `supersedes`, `superseded_by`, `consolidated_into`, `split_of`, `changes_from`, `comparable_with`.

- **Path targets.** A wikilink or embed (`![[...]]`) whose target contains `/` or ends in a file extension (e.g. `![[raw/papers/x.pdf]]`, `[[figures/roc.png]]`) is a vault-relative path, resolved against the filesystem, not the ID map. It does not count toward `orphan`.
- **Links survive model failure.** If the YAML parses but the model rejects it, links are still harvested from the raw frontmatter dict, so one bad field never makes other notes look orphaned. If the YAML itself is invalid, body wikilinks are still harvested. A note that fails to parse still registers its filename stem, so links *to* it do not break.
- Self-links are ignored.

### Reading and writing

- **Reads** use PyYAML's libyaml-backed safe loader (`CSafeLoader`, falling back to `SafeLoader`). Measured on 3,000 experiment frontmatters: PyYAML 0.47 s; ruamel `safe` 6.0 s (ruamel 0.19 no longer installs its C extension); ruamel round-trip 8.1 s. pydantic validates the resulting plain dict.
- **Writes** re-load the file in ruamel round-trip mode, mutate the `CommentedMap`, and dump with `indent(mapping=2, sequence=4, offset=2)` (Obsidian's property style), so key order, comments and quoting survive. `None` dumps as an empty value (`key:`), matching Obsidian. The body is passed through byte-for-byte.
- Writes go to a temp file in the same directory, then `os.replace`. No locking (one writer per working tree assumed).
- Tool edits set `updated` to today.

## 4. Schemas

### Common fields

`id, type, title, created, updated, author, status, tags: [], links: []`. Unknown fields allowed and preserved. Conditional requirements (e.g. `protocol` once `done`) are **not** enforced by the models except where noted; they belong to the lint rule that owns them (section 7).

### Per type

| Type | `status` enum | Type fields | Required H2 sections |
|---|---|---|---|
| experiment | planned, running, done, failed, superseded | hypothesis, protocol, tracker, code, config_hash, dataset, metrics, supersedes, superseded_by | Hypothesis, Setup, Results, Interpretation, Next |
| protocol | draft, frozen, retired | version, changes_from, comparable_with | Definition, Changes from previous version, Known caveats |
| claim | draft, supported, stale, retracted | statement, value, value_format, tolerance, evidence, protocol, manuscript_locations | Evidence summary, History |
| idea | open, consolidated, dropped | consolidated_into | — |
| concept | active, stale | sources (key required, may be empty) | Summary, Evidence, Open questions, Related |
| decision | proposed, accepted, superseded | supersedes, superseded_by | Context, Decision, Alternatives considered, Consequences |
| literature | active, stale | doi, arxiv, url, year, venue, relevance (high/medium/low) | Summary, Methods worth borrowing, Results to compare against, Style notes |
| handoff | final | agent, session_goal, files_touched | Done, In progress, Blockers, Next step for whoever picks this up |
| dataset | active, superseded | location, extracted, split_of, counts, protected, supersedes, superseded_by | Source, Inclusion and exclusion, Split definition, Known issues |

`literature` and `handoff` status enums are not given by the parent spec; the values above are the simplest choice (ADR).

Nested models: `tracker {backend, run_ids, url}`, `code {repo, sha, dirty}`, `metrics: [{name, value, split, run_id, as_of}]`.

**Model-enforced conditionals** (owned by `schema`): experiment `dataset` required when `status: done`; concept `sources` key present; `superseded_by` required when `status: superseded` (experiment, decision, dataset); idea `consolidated_into` required when `status: consolidated`.

Field types worth pinning: `created`/`updated`/`extracted`/`as_of` are dates; claim `value` is `float | list[float]`; `tolerance` is a non-negative float; `comparable_with`, `evidence`, `sources`, `links`, `tags` are lists of strings; `protocol` `version` is a positive int; `code.sha` is a 7–40 char hex string.

### Authorship

- *Agent-authored* = `author` is in `config.agents`.
- If `lab_members` is non-empty, `author` must be in `lab_members ∪ agents`; if empty, any author is accepted.
- Agent-authored notes must begin their body with `## For future agents` of at most 3 non-blank lines.

## 5. IDs (`ids.py`)

| Type | Format | Regex (default prefixes) |
|---|---|---|
| experiment, claim, idea, decision, dataset | `<P>-YYYYMMDD-<slug>` | `^(EXP\|CLM\|IDEA\|ADR\|DS)-\d{8}-<slug>$` |
| protocol | `EVAL-v<N>[-<slug>]` | `^EVAL-v\d+(-<slug>)?$` |
| literature | `LIT-<author><year>-<word>` | `^LIT-[a-z]+\d{4}-<slug>$` |
| handoff | `HO-YYYYMMDD-HHMM-<agent>` | `^HO-\d{8}-\d{4}-<slug>$` |
| concept | `<kebab-title>` | `^<slug>$` |

`<slug>` = `[a-z0-9]+(-[a-z0-9]+)*`, at most 40 chars **including** any collision suffix.

- `slugify`: NFKD-normalize, drop non-ASCII, lowercase, non-alphanumerics → `-`, collapse and trim hyphens, truncate at a word boundary. An empty result (e.g. a CJK-only author name) becomes `untitled` / `anon`.
- Collision check scans **every note folder** in the working tree, untracked files included (wikilinks are global, so IDs must be). Suffix `-2`, `-3`, … with the base slug truncated to keep the total ≤ 40.
- Protocol `new-id` picks `max(existing N) + 1`. This is the one counter in the system; protocols are created rarely and by a human, and a collision is caught by the duplicate-ID check.
- Date and time come from the local clock, injectable via `--at` / a `now` parameter.

## 6. CLI

```
labbrain [--vault PATH] <command> ...      # global; overrides LABBRAIN_VAULT and discovery
labbrain vault root
labbrain config [--key dotted.key]
labbrain new-id <type> --title T [--author A] [--at DATETIME]
labbrain new <type> --title T [--author A] [--link ID ...]
labbrain validate <path...> [--json]
labbrain sync [--dry-run] [--json]
labbrain index [--check]
labbrain log "<text>" [--author A]
labbrain lint [--json | --format github] [--base REF] [--rule R ...]
labbrain phi-scan <path...> [--json | --format github]
labbrain list [--type T] [--status S] [--tag X] [--json]
labbrain links <ID> [--in | --out] [--json]
labbrain config-hash <config.yaml|config.json>
labbrain schema [<type>]                 # JSON Schema of the frontmatter models
labbrain --version
```

`list` and `links` let skills and non-Claude agents query the graph without grepping YAML (`/brief`, `/consolidate` and the parent spec's `ideas list --open` become `list --type idea --status open`). `config-hash` implements the parent spec's section 9 hash now, so every caller hashes identically before `/exp-log` exists. `schema` exports pydantic's JSON Schema, so editors and other agents can validate frontmatter without Python. `--format github` emits `::error file=…,line=…::message` annotations for vault CI.

**Exit codes:** 0 = no error-severity findings (warnings allowed); 1 = at least one error; 2 = usage or configuration problem.

**JSON shape** (validate, sync, lint, phi-scan): `{"findings": [{"rule", "severity", "path", "line", "col", "message"}], "summary": {"errors": n, "warnings": n, "info": n}}`.

**`validate <path>`** is single-file and must not load the whole vault. Checks: parse, schema model, ID format, `id` = filename, author membership, duplicate filename (glob), `missing-section`, and phi when `protected_data`. Budget: < 300 ms. Because the M5 hook will call it on every write in the vault:
- A path inside the vault that is not a note (a `README.md`, a log file, a manuscript) gets only the phi check (when protected), never a schema error.
- A path outside the vault yields one `info` finding and exit 0.

**`phi-scan`** uses the vault's config when run inside one, otherwise defaults (`min_cell_size: 11`, no denylist), so it also works on non-vault trees such as this repo.

**Deterministic time:** every command reads `LABBRAIN_NOW` (ISO datetime) if set, else the local clock. Used by tests; documented as test-only.

**`new <type>`** mints an ID, writes a skeleton under the type's folder with every common and type field present (empty/null), the type's default status (experiment `planned`, protocol `draft`, claim `draft`, idea `open`, concept `active`, decision `proposed`, literature `active`, handoff `final`, dataset `active`), a `## For future agents` block if the author is an agent, and every required H2. Prints the path. Every skeleton passes `validate` with zero findings.

**`sync`** is idempotent and only performs allowed transitions:
1. For every note N with `supersedes: X`: set X `status: superseded`, `superseded_by: N`, bump `updated`. If X is already superseded by a different note, report an error and write nothing for X.
2. For every protocol referenced as `protocol` by a `done` experiment and still `draft`: set `status: frozen`.

**`index`** writes `index.md`: one `##` section per type in a fixed order, one line per note `- [[ID]] — title — summary`, newest `created` first, ties by ID. Summary = first sentence of the first paragraph after the `## For future agents` block, truncated to 160 chars; empty if none. Output is byte-deterministic. `--check` exits 1 if the file would change.

**`log`** appends `- HH:MM [author] text` to `log/YYYY-MM-DD.md` (no frontmatter, so the template can mark `log/` `merge=union`).

## 7. Lint rules

Each condition is owned by exactly one rule, so each broken fixture can trigger exactly one rule.

| Rule | Sev | Check |
|---|---|---|
| `schema` | error | Parse errors; model validation; ID format; `id` = filename; author membership; duplicate IDs; frontmatter-less file in a note folder; experiment `dataset` missing when `done`; concept `sources` key missing |
| `missing-section` | warning | Required H2s per type; `## For future agents` (≤3 lines) on agent-authored notes |
| `broken-link` | error | Every body wikilink and ID-bearing frontmatter value resolves to a note |
| `frozen-edit` | error | See below |
| `protocol-missing` | error | Experiment `status: done` with no `protocol` |
| `cross-protocol` | error | For each claim: every `evidence` experiment's `protocol` is comparable with the claim's `protocol` |
| `phi` | error | phi-scan findings not in the allowlist (only when `protected_data`) |
| `claim-stale` | warning | A claim's evidence experiment is `superseded` or `failed` |
| `concept-unsourced` | warning | Concept with `sources: []` |
| `orphan` | warning | Note with no inbound links; ideas and handoffs exempt |
| `inbox-age` | warning | Idea `open` and `created` older than `inbox_max_days` |
| `dirty-code` | warning | Experiment with `code.dirty: true` |
| `duplicate-config` | warning | Two non-superseded experiments share non-null `config_hash` and `protocol`, and neither directly supersedes the other |
| `undated-fact` | warning | See below |
| `index-stale` | warning | `index.md` exists and differs from generated output; skipped if absent (it is gitignored) |
| `sync-pending` | warning / error | `sync --dry-run` would change something (warning: someone forgot to run it, so `claim-stale` and the index are working from stale status). Conflicting supersession, where X is claimed by two successors, is an error |

`sync-pending` is a second addition to the parent rule table. Without it, a superseding note written by hand silently leaves its predecessor `done`, and `claim-stale` never fires.

### Comparability

`comparable(a, b)` ⇔ `a == b` or `b ∈ a.comparable_with` or `a ∈ b.comparable_with`. Symmetric because older protocols are frozen and cannot be edited to list newer ones; not transitive. Evidence experiments with no protocol, and evidence IDs that are not experiments, are skipped (other rules own them).

### `frozen-edit`

Compares the working tree against `--base` (default `HEAD`). Base versions are found **by ID** (filename), not path, so moves such as `ideas/inbox/ → ideas/archive/` are followed.

| Type | Frozen when, at base | Mutable frontmatter | Allowed status transitions |
|---|---|---|---|
| experiment | status ∈ {done, failed, superseded} | status, superseded_by, updated | done→superseded, failed→superseded |
| protocol | status ∈ {frozen, retired}, or referenced by a `done` experiment | status, updated | draft→frozen, frozen→retired |
| decision | status ∈ {accepted, superseded} | status, superseded_by, updated | accepted→superseded |
| dataset | always | status, superseded_by, updated | active→superseded |
| idea | always | status, consolidated_into, updated | open→consolidated, open→dropped |
| handoff | always | updated | — |

For a frozen note:
- **Frontmatter** is compared semantically (parsed values, key order ignored). Any change to a non-mutable field, or a status change not in the table, is an error.
- **Body**: `difflib.SequenceMatcher` over lines; only `equal` and `insert` opcodes allowed. Existing lines may never be modified or deleted; new lines may be inserted anywhere.
- **Deletion**: a frozen note present at base whose ID no longer exists anywhere in the working tree is an error.
- **`raw/`**: any file present at base must be byte-identical and not deleted.

Pre-commit compares against `HEAD` (the pre-commit framework stashes unstaged changes, so the working tree equals the staged tree). CI passes `--base <merge-base>` so commits made with `--no-verify` are still caught. Not a git repo, or `--base` does not resolve → one `info` finding and the rule is skipped.

**Implementation constraints:**
- **Diff-driven.** Only files reported by `git diff --name-status --no-renames <base> -- <vault>` can violate the rule; unchanged notes are never read from git. A `D` entry is a deletion unless its ID exists elsewhere in the working tree (a move); a moved note is then compared against its base blob.
- **Batched reads.** Base blobs are read through one `git cat-file --batch` process, never one `git show` per file. "Referenced by a `done` experiment at base" is computed only when a protocol is among the changed files.
- **Subfolder vaults.** `gitutil` resolves the repo top level and the vault's prefix inside it (`git rev-parse --show-toplevel`), so `brain/` inside a code repo works and code changes outside the vault are ignored.

### `undated-fact`

Applies to agent-authored **concept** and **claim** notes only (experiments are stamped through their own frontmatter; literature numbers come from the cited paper). For each body line outside code fences, headings and the `## History` section: if it contains a metric-like number (a percentage, or a decimal with ≥2 fractional digits), it must also contain one of: an `EXP-`/`LIT-`/`CLM-` wikilink, a `run_id`/`run:` token, or `as of YYYY-MM-DD`.

## 8. PHI scanner (`phi.py`)

### Rules

| Rule | Detects (default) |
|---|---|
| `phi-mrn` | 6–12 digit run within 30 chars of *MRN, medical record, record no, patient id, chart*; regex overridable via `phi.mrn_regex` |
| `phi-date` | Full date within 30 chars of *DOB, born, birth, admitted, discharged, date of service, visit* |
| `phi-phone` | NANP and E.164 formats with separators |
| `phi-email` | Email addresses |
| `phi-ssn` | `NNN-NN-NNNN` |
| `phi-address` | House number + name + street suffix (St, Ave, Rd, Blvd, Ln, Dr, …) |
| `phi-name` | Case-insensitive whole-word matches from the gitignored denylist file, if present |
| `phi-small-cell` | Table cells in a column headed n / N / count / patients / subjects with integer 1…`min_cell_size − 1`; inline `n = 5`, `N=5`, `5 patients` / `5 subjects` in that range. `<11`-style suppressed values pass. |

**Small-cell exemption for ML units.** ML notes say "n = 3 seeds" or "N=5 folds" constantly. An inline `n = k` immediately followed by a non-person unit (seeds, runs, folds, splits, epochs, layers, heads, models, trials, replicates, GPUs, nodes, steps, batches, tokens, classes, tasks, checkpoints, iterations, configs, sweeps). "samples" is deliberately **not** exempt: in clinical work it often means patients' samples is not flagged. A bare `n = 5`, or one followed by a person word, is flagged; that errs toward false positives, as the parent spec requires. Table columns headed `n` are always checked; a column of seed counts belongs under a header like `seeds`.

Scope: every text file in the vault except `scratch/`, any dot-directory (`.git/`, `.labbrain/`, `.obsidian/`, `.claude/`: config, hashes and tool state, not prose), `__pycache__/`, `index.md` and binary files (null byte in the first 8 KB, or `raw/**/*.pdf`). Manuscripts **are** scanned.

### Output never contains matched text

Findings render as `path:line:col rule (span: N chars)`, with **no line text at all**, since an unmatched part of the line may hold an identifier the patterns missed. The same applies to JSON.

### Allowlist (`.labbrain/phi-allow.yaml`)

```yaml
- {file: concepts/foo.md, rule: phi-phone, line_sha256: "<first 16 hex>", line_hint: 42,
   author: alice, date: 2026-10-15, reason: "version string, not a phone number"}
```

Matched by `file + rule + sha256(line with surrounding whitespace stripped)`. Survives edits elsewhere in the file; forces re-review when the line itself changes; whole-line hashes are not practically reversible, unlike a hash of a short identifier. `line_hint` is informational only. (Deviation from the parent spec's `file:line:rule`; ADR.)

### Error-message sanitization

Validation errors are a second leak path, because the PostToolUse validator feeds output back into model context:
- pydantic errors are rendered from `errors(include_input=False, include_url=False)` as `loc: msg`.
- ruamel parse errors are reduced to `frontmatter is not valid YAML (line N)`.
- Custom validators never interpolate field values into messages.
- `findings.sanitize()` is applied to every message before output.

## 9. Testing

### Fixtures

- `tests/fixtures/valid/`: static vault with `.labbrain/config.yaml`, one note of each type, every note (except ideas/handoffs) linked from another, a current `index.md`, an empty allowlist.
- `tests/fixtures/mutations.py`: one function per rule, `(vault_dir) -> None`, registered with the rule it must trigger. A pytest fixture copies `valid/` to `tmp_path`, `git init`s and commits it (needed for `frozen-edit`), then applies the mutation. Extra mutations cover sub-cases (status laundering, deletion, idea move, `raw/` edit, symmetric `comparable_with`, PHI per pattern).

Harness rules that keep "exactly one rule fires" true:
- **The valid fixture is always tested from a `tmp_path` copy with its own `git init`.** `tests/fixtures/valid/` sits inside the engine repo, so running git commands there would diff against the engine's own history.
- **The harness deletes `index.md` after every mutation except the `index-stale` one.** Almost any edit changes a title or summary and would otherwise also trip `index-stale`.
- **Every mutation except a `frozen-edit` one is committed before linting**, so `base == working tree` and `frozen-edit` sees no diff. Mutations can then edit frozen notes naturally (e.g. stripping `protocol` from a done experiment for `protocol-missing`). `frozen-edit` mutations are left uncommitted.
- **Every non-exempt note in the valid fixture has at least two inbound links**, so a mutation that removes one link never creates an orphan.
- **The deletion mutation removes a handoff or idea**, which are always frozen and need no inbound links. Deleting a linked note would correctly also fire `broken-link`.
- **The `schema` mutations keep the YAML parseable** (bad enum, wrong type, `id` ≠ filename), plus one invalid-YAML mutation on the literature note, which has no ID-bearing frontmatter, so losing its frontmatter drops no links.
- **Each mutation's docstring says why no other rule fires.** Reviewers check that claim, not the code.

### Gate tests

- Valid fixture: zero findings at **every** severity, with `today` pinned.
- Each mutation: `{f.rule for f in findings} == {declared_rule}`, all severities.
- `validate` on every valid note: zero findings. `index --check` on the valid fixture: exit 0.
- `labbrain new <type>` for all nine types: skeleton passes `validate` with zero findings.
- `sync` on a fixture with a pending supersession: second run is a no-op; output passes `frozen-edit`.
- ruamel round-trip: changing one field changes exactly one line of the file.
- An idea moved inbox → archive with an allowed status change: no `frozen-edit` finding.
- Subfolder vault (`brain/` inside a repo with code commits): `frozen-edit` checks only vault files.
- `config-hash`: key order, nesting style and `hash_ignore` keys do not change the hash; any other value change does.
- `.pre-commit-hooks.yaml`: `pre-commit try-repo .` runs both hooks against the valid fixture (CI only; skipped if `pre-commit` is not installed).

### PHI tests

- Identifiers are generated in-test from a seeded RNG and written only under `tmp_path`.
- For each pattern: the finding is raised, and the generated string does not appear in stdout, stderr or `--json` output.
- Leak paths: a synthetic MRN in a malformed frontmatter field and in invalid YAML; the value must not appear in `validate` output.
- Allowlist: an entry suppresses its finding; inserting lines above keeps it suppressed; editing the line un-suppresses it.
- Meta-test: `phi-scan` over the repo excluding `tests/` yields zero findings.

### Performance (`@pytest.mark.slow`)

A generated 3,000-note vault: `lint` < 3 s; `validate` on one file < 300 ms.

### Coverage and CI

pytest-cov with `fail_under = 85` over `schema`, `ids`, `lint`, `phi`, `vault`. GitHub Actions: `uv sync`, `ruff check`, `ruff format --check`, `pytest` on Python 3.11 and 3.13. Slow tests run in CI.

## 10. ADRs to record in `docs/decisions/`

Recorded as eight grouped ADRs (layout; lint rule set; frozen-edit; PHI; CLI and dependencies; sync and new; schema details; fixtures), each listing which items below it covers.

1. `lint/` package and `findings.py` (deviation from parent tree)
2. `missing-section` warning rule (addition to parent rule table)
3. `cross-protocol` structured-only, claims only
4. `undated-fact` scope: agent-written concepts and claims, line-local
5. `frozen-edit` semantics: transition table, insert-only body, ID-keyed lookup, deletions, `--base`
6. Rule-ownership resolutions for the three overlapping conditions in the parent spec
7. PHI allowlist keyed by whole-line hash; findings never contain line text
8. argparse over typer; lazy imports (hook latency)
9. `labbrain sync` (fills the parent spec's unassigned "the tool then sets…")
10. `labbrain new` (scaffolding from schema)
11. ruamel.yaml round-trip writes
12. Python ≥ 3.11
13. Mutation-based broken fixtures
14. `literature` and `handoff` status enums; protocol numbering as the one counter
15. `sync-pending` lint rule (second addition to parent rule table)
16. Query and utility commands: `list`, `links`, `config-hash`, `schema`, `--format github`, `.pre-commit-hooks.yaml`
17. Small-cell exemption for ML unit words
18. Path-style wikilinks and embeds resolve against the filesystem

## 11. Notes for later sub-projects

- **Template (2):** gitignore `index.md` and `scratch/`; `.gitattributes` `log/** merge=union`; render `config.yaml` from the section 3 model; generate `templates/` examples via `labbrain new`. Open decisions to settle: tracker default, vault location.
- **Plugin/hooks (3):** call `labbrain validate` (budget 300 ms) from PostToolUse; frozen-file hook reuses `frozen_rules` logic; `claude` CLI is not on this machine's PATH yet (needed for headless smoke tests). Open decision: how much `_kit/` skill wording to reuse from `/Users/jbotas/kb-vault/_kit`.
- **Claims/literature (4):** claims are not frozen, but `## History` append discipline could become a rule. Open decision: manuscript format.
- **Before first push:** GitHub org and repo visibility.

## 12. Changelog

- 2026-10-15: Initial design from brainstorming.
- 2026-10-15: Self-review amendments.
  - Gate-safety harness rules: commit non-`frozen-edit` mutations; delete `index.md`; two inbound links per note.
  - Links survive model or parse failure; path-style wikilinks resolve against the filesystem.
  - `frozen-edit` is diff-driven, batched and subfolder-aware.
  - `validate` handles non-note paths and paths outside the vault.
  - `phi-scan` runs outside a vault and skips `.labbrain/`; small-cell exemption for ML units.
  - Added conditional schema requirements (`superseded_by`, `consolidated_into`) and pinned field types.
  - Added the `sync-pending` rule.
  - Added `list`, `links`, `config-hash`, `schema`, `--format github`, `--version`, `.pre-commit-hooks.yaml` and `LABBRAIN_NOW`.
- 2026-10-15: Planning amendments.
  - Reads use the C-backed safe loader; round-trip only on write.
  - Global `--vault` option for subfolder vaults under pre-commit.
  - JSON findings include `col`.
  - "samples" removed from the small-cell exemption list.
  - phi-scan skips all dot-directories.
  - Added `layout.py`, `validate.py` and `__main__.py`.
  - ADRs grouped into eight files.
  - Reads switched from ruamel `safe` to PyYAML `CSafeLoader` after benchmarking (adds `pyyaml>=6`).
