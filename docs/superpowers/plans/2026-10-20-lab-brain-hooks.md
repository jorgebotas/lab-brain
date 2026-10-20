# lab-brain M5 Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship engine and plugin v0.3.0 with Claude Code hooks (data guard, frozen-file guard, write validator, session brief), then template v0.3.0 pinning it.

**Architecture:**
- `hooks/hooks.json` in the plugin runs `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain hook <event>` for three events: PreToolUse, PostToolUse and SessionStart.
- `labbrain/hooks/` holds one module per concern behind a single entry point, `run_hook`. Each event is a single process that only ever exits 0 or 2.
- Wave 1 builds the entry point, payload parsing, vault scope and protected-path containment, plus stub modules with their final signatures.
- Wave 2 fills the four stubs in parallel worktrees: file-tool guard, Bash analysis, frozen and PHI write checks, post-write validation and session start.
- Wave 3 integrates, documents and releases. Phase B updates the template.

**Tech Stack:** Python 3.11+ (stdlib `shlex`, `unicodedata`, `os.scandir`), existing deps only (pydantic, pyyaml, ruamel.yaml), pytest, uv, Claude Code plugin hooks.

**Spec:** `docs/superpowers/specs/2026-10-20-lab-brain-hooks-design.md`. Section numbers below (§N) refer to it. Every implementer reads the sections their task names.

## Global Constraints

- **Exit codes.** `labbrain hook …` exits only 0 (allow or nothing to report) or 2 (deny or report, reason on stderr). Never any other code.
- **Never emit an allow.** No hook ever writes a `permissionDecision` (or any JSON decision) to stdout. Hooks deny via exit 2 or stay silent.
- **Fail closed** on the PreToolUse path. Malformed or oversized stdin, an engine exception, or a broken vault config all deny.
- **Fixed failure messages.**
  - Pre-tool-use: `lab-brain guard failed; blocked to be safe`
  - Post-tool-use: `lab-brain validator failed`
- **Data-denial message,** exact copy: `lab-brain data guard: {subject} refers to protected data path #{n} ('{configured}'). Individual-level data must not enter the session. If you need this run, ask the user to run it themselves and share only aggregate results.`
  - `{subject}` is e.g. `this Bash command` or `this Read call`.
  - `n` is the entry's 1-based position in its vault's `data_paths`.
  - `configured` is the entry as configured.
- **What output may never contain.** No hook output, stdout or stderr, may contain:
  - the command text, a candidate path, a file name under a data path, or file contents;
  - PHI matched text;
  - frontmatter values other than note IDs;
  - a traceback.
- **No pydantic on the no-vault path.** `labbrain.vault` must not be imported when no vault is found. Heavy modules (`lint`, `phi`, the frozen module) are imported only on paths that need them.
- **No new runtime dependencies.**
- **Code style.** Python ≥ 3.11, type hints on all functions, and `ruff check .` plus `ruff format --check .` clean (line length 100).
- **Identifiers.** Real-looking identifiers only under `tests/` and `docs/superpowers/`. Synthetic sentinels are generated in tests.
- **Commits.** Conventional, and every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Stage new files before the full suite.** `tests/test_precommit.py` runs `pre-commit try-repo`, which sees only tracked or staged files, so stage new modules before running the full suite.
- **Full suite.** `uv run pytest` (smoke tests are excluded by default) passes, with coverage ≥ 85% on the coverage include list. Task 1 adds `*/labbrain/hooks/*` to that list.

## Review Focus

1. **A data path given relatively in the engine config.** The engine accepts relative entries; only the template forbids them. Expected: `data_paths: ["data"]` in a hand-written config is resolved against the vault root and guarded like an absolute one. Test: Task 1, `test_relative_data_path_resolved_against_vault`.
2. **A protected root that does not exist yet**, for example a mount that is not attached. Expected: still guarded, by canonical text and casefold; the identity check is simply skipped. Test: Task 1, `test_missing_root_still_contains`.
3. **A Write to a brand-new note file in a protected vault containing PHI.** Expected: denied before it lands, even though the file does not exist yet. Test: Task 4, `test_phi_prescan_new_file`.
4. **A Bash command with a quoted path containing spaces** (`cat "/mnt/phi data/f.csv"`). Expected: denied; the lexer keeps the quoted word whole. Test: Task 3 corpus row `quoted-space`.
5. **Two vaults in scope, for example a subfolder vault plus `LABBRAIN_VAULT` pointing to another, with one broken config.** Expected: the broken one makes everything deny (except a Read of its `.labbrain/`), and the healthy one's roots are still checked. Test: Task 2, `test_broken_vault_among_two`.

---

## Execution waves

| Wave | Tasks | How |
| --- | --- | --- |
| 1 | Task 1 | Alone, on `feat/m5-hooks` |
| 2 | Tasks 2, 3, 4, 5 | In parallel. Each on its own branch from Task 1's head, in its own worktree **outside** the repo directory (e.g. `/Users/jbotas/Documents/lab-brain-wt-m5-t<N>`). Each owns disjoint files (listed per task). Merge back with `--no-ff` in order 2, 3, 4, 5. |
| 3 | Task 6 | Alone, after the merges |
| B | Task 7 | In `lab-brain-template`, only after engine v0.3.0 is merged and tagged |

Wave 2 tasks must not edit files that another task owns. In particular, only Task 1 edits `tests/helpers.py` and `labbrain/hooks/entry.py`. A wave-2 task that needs a new test helper defines it in its own test file.

---

### Task 1: Hook entry point, payloads, scope, containment, hooks.json

**Files:**
- Create:
  - `labbrain/hooks/__init__.py` (empty docstring module);
  - `labbrain/hooks/payload.py`, `labbrain/hooks/paths.py`, `labbrain/hooks/scope.py`, `labbrain/hooks/entry.py`;
  - stubs `labbrain/hooks/guard.py`, `labbrain/hooks/bash.py`, `labbrain/hooks/writes.py`, `labbrain/hooks/post.py`, `labbrain/hooks/session.py`;
  - `hooks/hooks.json`;
  - `tests/fixtures/hooks/{read,write,edit,bash,session_start,post_write}.json`;
  - `tests/test_hook_entry.py`, `tests/test_hook_paths.py`, `tests/test_hook_scope.py`.
- Modify:
  - `labbrain/cli.py` (add `hook` subcommand);
  - `pyproject.toml` (add `"hooks"` to sdist `only-include`, and `*/labbrain/hooks/*` to the coverage include);
  - `tests/helpers.py` (add `hook_payload`);
  - `tests/test_plugin_manifest.py` (hooks.json checks).

**Interfaces (produced; later tasks rely on these exact names):**

`labbrain/hooks/payload.py`:
```python
MAX_STDIN: int = 4 * 1024 * 1024
class PayloadError(Exception): ...
@dataclass(frozen=True)
class Payload:
    event: str                 # hook_event_name
    tool_name: str             # "" for SessionStart
    tool_input: dict[str, Any] # {} when absent
    cwd: Path                  # absolute, from the payload
    session_id: str
    source: str                # SessionStart source, "" otherwise
def parse_payload(data: bytes) -> Payload   # raises PayloadError: not JSON, not an object,
                                            # missing/odd cwd, tool_input not an object, > MAX_STDIN
@dataclass(frozen=True)
class Denial:
    rule: str      # one of: "data-guard", "guard-config", "frozen-file", "phi", "config"
    message: str   # already sanitized, single paragraph
def data_denial(root: "ProtectedRoot", subject: str) -> Denial   # exact copy from Global Constraints
```

`labbrain/hooks/paths.py` (stdlib only):
```python
def canonical(p: Path | str, base: Path | None = None) -> Path  # expanduser; join to base if relative; resolve(strict=False)
def fold(p: Path | str) -> str                                  # unicodedata NFC then casefold
@dataclass(frozen=True)
class ProtectedRoot:
    vault: Path; index: int; configured: str; path: Path        # path canonical
@dataclass(frozen=True)
class GuardFile:
    path: Path; tree: bool                                      # tree=True: path and everything below
class Targets:
    def __init__(self, roots: Sequence[ProtectedRoot], guard_files: Sequence[GuardFile]) -> None
    roots: tuple[ProtectedRoot, ...]
    def containing(self, p: Path) -> ProtectedRoot | None  # p (canonicalised) inside or equal a root, by
        # canonical prefix, by fold() prefix, or by (st_dev, st_ino) of p or a parent matching a root
    def under(self, p: Path) -> list[ProtectedRoot]        # roots strictly below canonical p (fold compare)
    def is_guard_file(self, p: Path) -> bool               # fold compare; tree entries match descendants
```

`labbrain/hooks/scope.py`:
```python
def find_vault_roots(cwd: Path, env: Mapping[str, str]) -> list[Path]
    # stdlib only, deduplicated by canonical path, in this order:
    #   the vault containing cwd;
    #   the vault containing $CLAUDE_PROJECT_DIR;
    #   $LABBRAIN_VAULT (a relative value is joined to $CLAUDE_PROJECT_DIR, else to cwd).
    # A vault is a directory with .labbrain/config.yaml. A $LABBRAIN_VAULT without one is ignored here.
def vault_of(path: Path) -> Path | None                  # stdlib-only ancestor search from path's parent
@dataclass(frozen=True)
class VaultInfo:
    root: Path; config: "Config | None"; broken: bool    # broken: load_config raised ConfigError (or any error)
@dataclass(frozen=True)
class Scope:
    vaults: tuple[VaultInfo, ...]
    targets: Targets
    agents: frozenset[str]          # union of configs' `agents`
    protected: bool                 # any vault protected_data true with ≥1 data path, or any broken
    project_dir: Path | None
    @property
    def broken(self) -> tuple[VaultInfo, ...]
def load_scope(cwd: Path, env: Mapping[str, str]) -> Scope   # imports labbrain.vault only when roots exist
```

Guard files (§5, "Guard self-protection") are built only for protected scopes:
- per vault: `.labbrain` (tree) and `.copier-answers.yml`;
- `.claude/settings.json` and `.claude/settings.local.json` under each vault, under `project_dir` and under `~/.claude`;
- trees: `$CLAUDE_PLUGIN_ROOT` (if set), `~/.claude/plugins`, and the uv cache (`$UV_CACHE_DIR`, else `~/.cache/uv`).

Stub signatures. Wave 2 replaces the bodies; the stubs return "nothing found":
```python
# guard.py   (Task 2)
def check_tool(payload: Payload, scope: Scope) -> Denial | None
# bash.py    (Task 3)
def check_command(command: str, cwd: Path, scope: Scope, env: Mapping[str, str], session_id: str) -> Denial | None
# writes.py  (Task 4)
def check_write(payload: Payload, scope: Scope) -> Denial | None
# post.py    (Task 5)
def post_tool_use(payload: Payload, env: Mapping[str, str]) -> tuple[int, str]   # (exit code, stderr text)
# session.py (Task 5)
def session_start(payload: Payload, env: Mapping[str, str]) -> tuple[int, str, str]  # (code, stdout, stderr)
```

`labbrain/hooks/entry.py`:
```python
EVENTS = ("pre-tool-use", "post-tool-use", "session-start")
def run_hook(event: str, stdin: bytes, env: Mapping[str, str]) -> tuple[int, str, str]  # (code, stdout, stderr)
```

**pre-tool-use:**
1. `parse_payload` (a `PayloadError` denies).
2. `load_scope(payload.cwd, env)`.
3. `guard.check_tool`, then `writes.check_write`. The first Denial gives exit 2 with `denial.message`.
4. Otherwise exit 0 with empty output.
5. Any exception (including `PayloadError`) exits 2 with the fixed pre message. The exception is never printed.

**post-tool-use:** delegates to `post.post_tool_use`. A `PayloadError` or any exception exits 2 with the fixed post message.

**session-start:** delegates to `session.session_start`. A `PayloadError` or any exception exits 2 with `lab-brain session brief failed`.

**CLI:** `labbrain hook {pre-tool-use,post-tool-use,session-start}`, through `cmd_hook`:
- reads at most `MAX_STDIN + 1` bytes from `sys.stdin.buffer`;
- calls `run_hook(event, data, os.environ)`;
- writes stdout and stderr, and returns the code.

**`hooks/hooks.json`:** as §4, with these values:
- PreToolUse: matcher `"*"`, timeout 120, `"onFailure": "block"`, command ending `|| exit 2`.
- PostToolUse: matcher `"Write|Edit|MultiEdit|NotebookEdit"`, timeout 120, command ending `|| exit 2`.
- SessionStart: no matcher, timeout 60, no `|| exit 2`.
- Every command starts `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain hook `.

**Fixtures:** one JSON object per file, with the exact key sets recorded on CLI 2.1.284 (§3). Strings `{cwd}`, `{path}` and `{command}` are placeholders.
- Read: `session_id, transcript_path, cwd, permission_mode, hook_event_name, prompt_id, scratchpad_dir, tool_name, tool_input{file_path}, tool_use_id`.
- Write: the same, with `tool_input{file_path, content}`.
- Edit: `tool_input{file_path, old_string, new_string, replace_all}`.
- Bash: `tool_input{command, description}`.
- SessionStart: `session_id, transcript_path, cwd, hook_event_name, scratchpad_dir, source`.
- PostToolUse Write: the Write keys plus `duration_ms` and `tool_response{type, filePath, content, structuredPatch, originalFile, userModified}`.

`tests/helpers.py`:
```python
def hook_payload(name: str, **subs: Any) -> bytes
    # loads tests/fixtures/hooks/<name>.json, replaces "{key}" placeholders in every string
    # with str(value) (keys: cwd, path, command, content, old, new, source; unspecified
    # placeholders stay literal), applies overrides passed as tool_input=dict, tool_name=str, and
    # returns UTF-8 JSON bytes
```

- [ ] **Step 1: Write the failing tests**

`tests/test_hook_paths.py`:
- `test_containing_by_prefix`: a root `R`. `containing(R/"a/b")` is that root; `containing(R)` is that root; `containing(R.parent/"other")` is None.
- `test_containing_through_symlink`: link `vault/l -> R`. `containing(vault/"l/f")` is that root.
- `test_containing_dotdot`: `containing(R/"x/../y")` is that root; `containing(R/"..")` is None.
- `test_containing_casefold`: a root at `…/Data`. `containing(Path(str(R).replace("Data", "dATA"))/"f")` is that root.
- `test_containing_by_identity`: monkeypatch `paths._identity` so a differently spelled path has the root's identity. It is contained.
- `test_missing_root_still_contains` (Review Focus 2): a root that does not exist. A path below it is contained.
- `test_under_strict`: `under(R.parent)` contains the root; `under(R)` is empty.
- `test_guard_file_tree_and_exact`: tree entries match descendants; exact entries match only themselves (fold compare).

`tests/test_hook_scope.py`:
- `test_no_vault_does_not_import_pydantic`: in a subprocess with cwd an empty dir, run `run_hook("pre-tool-use", <bash payload>, env)` and then print `'pydantic' in sys.modules`. It prints `False`, and the code is 0.
- `test_union_of_cwd_project_and_env`:
  - three vaults A (contains cwd), B (`CLAUDE_PROJECT_DIR`) and C (`LABBRAIN_VAULT`) give the roots `[A, B, C]`;
  - a relative `LABBRAIN_VAULT="brain"` resolves against `CLAUDE_PROJECT_DIR`, not cwd, when cwd is a subdirectory.
- `test_relative_data_path_resolved_against_vault` (Review Focus 1): `data_paths: ["data"]` gives a root of `vault/"data"`.
- `test_broken_config_marks_vault_broken_and_protected`.
- `test_guard_files_listed_only_when_protected`.

`tests/test_hook_entry.py`:
- `test_bad_json_denies`: `run_hook("pre-tool-use", b"not json", {})` gives `(2, "", "lab-brain guard failed; blocked to be safe")`.
- `test_oversized_stdin_denies`.
- `test_exception_denies_without_traceback`: monkeypatch `guard.check_tool` to raise `RuntimeError("SECRET")`. The code is 2, stderr is the fixed message, and `"SECRET"` and `"Traceback"` appear in no output.
- `test_denial_message_is_stderr_and_exit_2`: monkeypatch `guard.check_tool` to return a Denial. The code is 2, stderr equals the message, stdout is empty.
- `test_allow_is_silent`: no vault, a Read payload, gives `(0, "", "")`.
- `test_post_and_session_failures_use_fixed_messages`.
- `test_cli_hook_subcommand`: `subprocess.run([sys.executable, "-m", "labbrain", "hook", "pre-tool-use"], input=b"{}")` exits 2.
- `test_data_denial_copy`: `data_denial(ProtectedRoot(v, 1, "~/phi", p), "this Read call").message` equals the exact copy from Global Constraints.

`tests/test_plugin_manifest.py`, add `test_hooks_json`:
- it parses;
- PreToolUse has one entry with matcher `"*"`, `onFailure == "block"`, and a command ending `|| exit 2`;
- PostToolUse has the matcher `"Write|Edit|MultiEdit|NotebookEdit"` and ends `|| exit 2`;
- SessionStart has no `|| exit 2`;
- every command starts `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain hook ` and names an event in `entry.EVENTS`;
- and `"hooks"` is in the sdist `only-include`.

- [ ] **Step 2: Run them, expect failures** (`ModuleNotFoundError: labbrain.hooks`)

Run: `uv run pytest tests/test_hook_entry.py tests/test_hook_paths.py tests/test_hook_scope.py tests/test_plugin_manifest.py -q`

- [ ] **Step 3: Implement the interfaces above.** Approach:
  - `paths._identity` mirrors `trackers/local._identity`.
  - `Targets.containing` checks the candidate and each of its parents against the root identities captured at construction.
  - `scope.find_vault_roots` and `vault_of` use only `os.path`/`pathlib` and `layout.CONFIG_PATH` (`layout` is stdlib-only).
  - `load_scope` imports `labbrain.vault.load_config` lazily, and catches every exception from it as "broken".
  - The data roots come from `protected_roots`-style resolution: `resolve_config_path(root, entry)`, then `canonical`.
- [ ] **Step 4: Run the tests, expect PASS;** then stage everything and run `uv run pytest -q` and both ruff checks.
- [ ] **Step 5: Commit** — `feat(hooks): hook entry point, payload parsing, vault scope and hooks.json`

---

### Task 2: Data guard for file tools, MCP tools, broken config, file-tool self-protection

**Owns:** `labbrain/hooks/guard.py`, `tests/test_hook_guard.py`.

**Interfaces:**
- Consumes: `Payload`, `Denial`, `data_denial` (payload.py); `Scope`, `Targets` (Task 1); `bash.check_command` (stub in this branch, real after Task 3).
- Produces: `check_tool(payload: Payload, scope: Scope) -> Denial | None` and `SKIP_TOOLS: frozenset[str]`.

**Behaviour** (§4 "Failures in a vault's own setup", and §5 "Decision per tool" and "Guard self-protection"), checked in this order:
1. `not scope.protected`: return None.
2. **Broken vault in scope.** Allow only `tool_name == "Read"` whose `file_path` is inside a broken vault's `.labbrain/`.
   - Otherwise deny, rule `config`, message: `lab-brain guard: this vault's .labbrain/config.yaml could not be loaded, so protected data paths are unknown and every tool call is blocked. Ask the user to fix .labbrain/config.yaml (labbrain lint shows the problem).`
3. **Payload `cwd` inside a protected root:** deny, with subject `this session's working directory`.
4. **Per tool:**
   - **Read, Write, Edit, MultiEdit, NotebookEdit, NotebookRead, LS:** check the paths in `file_path`, `notebook_path` and `path`, joined to cwd when relative.
   - **Grep:** the search root (`path`, default cwd) is denied when `containing` it, or when `under` it is non-empty. Any root whose spelling appears in `glob` is also denied.
   - **Glob:** literal prefix of `path/pattern` up to the first component with `*?[{`.
     - If the prefix is contained: deny.
     - If `under(prefix)` is non-empty: deny when the remaining pattern contains `**`, or when `fnmatch`es its components against the root's relative path.
   - **Bash:** `return bash.check_command(command, payload.cwd, scope, env=os.environ, session_id=payload.session_id)`.
   - **`SKIP_TOOLS`:** return None. The list is `Agent, Task, TodoWrite, ToolSearch, Skill, AskUserQuestion, WebSearch, ExitPlanMode, EnterPlanMode, SendMessage, TaskStop, ScheduleWakeup`.
   - **Anything else, including `mcp__*`:** walk `tool_input` recursively (depth ≤ 20, ≤ 2,000 strings, strings ≤ 4,096 chars, longer ones truncated).
     - Each string is a candidate: absolute or `~` directly, relative joined to cwd.
     - Also deny when a root's configured, `~`-expanded or canonical spelling occurs in the string (fold compare).
5. **File-tool self-protection.** Write, Edit, MultiEdit and NotebookEdit whose target `scope.targets.is_guard_file`: deny, rule `guard-config`, message: `lab-brain guard: agents may not change lab-brain or Claude Code guard settings in a protected vault. Ask the user to make this change.`

Subjects: `this {tool_name} call`.

- [ ] **Step 1: Failing tests**

`tests/test_hook_guard.py`, using a protected vault built with `make_vault`. The config has `protected_data: true` and `data_paths: [<tmp>/phi]`; `phi/rows.csv` contains a sentinel generated with `secrets.token_hex`.
- `test_read_inside_root_denied`, `test_read_symlink_into_root_denied`, `test_read_dotdot_escape_denied`, `test_read_outside_root_allowed`
- `test_write_and_edit_into_root_denied`
- `test_unprotected_vault_allows_everything`
- `test_cwd_inside_root_denies_any_tool`
- `test_grep_from_ancestor_denied`, `test_grep_inside_root_denied`, `test_grep_elsewhere_allowed`
- `test_glob_star_star_from_ancestor_denied`, `test_glob_shallow_from_ancestor_allowed`, `test_glob_absolute_into_root_denied`
- `test_mcp_nested_argument_denied`: `tool_input={"args": {"files": ["<root>/rows.csv"]}}`.
- `test_mcp_unrelated_allowed`
- `test_skip_tools_not_scanned`: an Agent prompt mentioning the root is allowed.
- `test_broken_config_only_read_of_labbrain_allowed`: a Read of `.labbrain/config.yaml` is allowed. Denied: a Read elsewhere, an Edit of `config.yaml`, and Bash `labbrain lint`.
- `test_broken_vault_among_two` (Review Focus 5)
- `test_guard_files_write_denied`: Edits of `.labbrain/config.yaml`, `.copier-answers.yml`, `.claude/settings.json`, and a file under `CLAUDE_PLUGIN_ROOT`, are all denied with rule `guard-config`. A Read of the same files is allowed.
- `test_messages_never_leak`: for every denial above, the sentinel, the file name `rows.csv` and the full candidate path are absent from `message`, and the message names `#1` and the configured entry.

- [ ] **Step 2: Run, expect failures.** `uv run pytest tests/test_hook_guard.py -q`
- [ ] **Step 3: Implement `check_tool`.**
- [ ] **Step 4: Run the tests, expect PASS;** then `uv run pytest -q` and ruff.
- [ ] **Step 5: Commit** — `feat(hooks): data guard for file and MCP tools, broken-config and settings protection`

---

### Task 3: Bash analysis and link exposure

**Owns:** `labbrain/hooks/bash.py`, `labbrain/hooks/exposure.py`, `tests/test_hook_bash.py`, `tests/test_hook_exposure.py`.

**Interfaces:**
- Consumes: `Scope`, `Targets`, `Denial`, `data_denial` (Task 1).
- Produces:
```python
# bash.py
def check_command(command: str, cwd: Path, scope: Scope, env: Mapping[str, str], session_id: str) -> Denial | None
RECURSIVE: Mapping[str, ...]; FOLLOWING: Mapping[str, ...]; INTERPRETERS: frozenset[str]   # the §5 lists, in one place
# exposure.py
WALK_LIMIT: int = 20_000
SKIP_DIRS: frozenset[str] = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"})
@dataclass(frozen=True)
class LinkScan:
    found: bool; truncated: bool
def links_under(start: Path, targets: Targets, cache_dir: Path | None, session_id: str) -> LinkScan
    # os.scandir walk, no link following, skips SKIP_DIRS and protected roots; a symlink whose
    # target canonicalises inside a root sets found. Stops at WALK_LIMIT entries (truncated).
    # Cache: <cache_dir>/exposure/<sha256(session_id)[:16]>.json mapping canonical start → result;
    # cache_dir is $CLAUDE_PLUGIN_DATA (None: no cache). A cache that fails to read or parse is ignored.
```

**Behaviour:**
- Data rules 1–8 of §5 apply when the scope has roots, plus the Bash half of self-protection when `scope.protected`:
  - a candidate naming a guard file;
  - a `copier` program word;
  - a program word equal to `claude` or in `scope.agents`.
- **One exemption from the guard-file rule:** the exact value of `--from` after a `uvx` program word, when it canonicalises to `$CLAUDE_PLUGIN_ROOT`. That is how every skill runs the engine. Any other candidate inside the plugin root still denies, and so does the root itself in any other position.
- **Self-protection message** (rule `guard-config`): `lab-brain guard: this Bash command would change lab-brain or Claude Code guard settings, or start a nested agent, in a protected vault. Ask the user to run it.`
- **Unconfident message** (rule 8 and the leading-wildcard part of rule 2), rule `data-guard`: `lab-brain data guard: this Bash command cannot be checked safely (it uses an unresolved variable, a command substitution, or dynamic evaluation) in a protected vault. Spell paths out, or ask the user to run it themselves.`
- **Program words:** the first word of each simple command after splitting on `;`, `&&`, `||`, `|`, `&`, newlines and `(`/`)`. Skip leading `NAME=value` assignments and the wrappers `env`, `command`, `nice`, `time`, `sudo`, `xargs`. A program given by path is matched on its basename.
- **The rule 6a `rg` exception:**
  - calls `git -C <start> check-ignore -q <root>` for each root under the start;
  - the exception applies only when every one of them exits 0;
  - a git failure means "not ignored".
- **The rule 6b link check:** calls `links_under(start, scope.targets, Path(env["CLAUDE_PLUGIN_DATA"]) if set else None, session_id)`. A truncated walk denies any recursive construct from that start.

- [ ] **Step 1: Failing tests**

`tests/test_hook_bash.py` is table-driven. A `CASES` list holds `(case_id, command, expected)`, where expected is `"deny"` or `"allow"`. It runs against a protected scope with root `R = <tmp>/mnt/phi`; vault `V = <tmp>/repo/brain`; code repo `<tmp>/repo` (git init); cwd `<tmp>/repo`. `$HOME` is monkeypatched to `<tmp>/home`, and `R` is also reachable as `~/phi` through a home symlink.

Rows that must deny:
- `cat-abs`: `cat {R}/rows.csv`
- `head-tilde`: `head -5 ~/phi/rows.csv`
- `home-var`: `wc -l $HOME/phi/rows.csv`
- `rel-dotdot`: `cat ../mnt/phi/rows.csv`
- `quoted-space`: `cat "{R} data/f.csv"`, with a root `"{R} data"` added
- `python-c`: `python -c "print(open('{R}/rows.csv').read())"`
- `duckdb`: `duckdb -c "select * from '{R}/rows.csv'"`
- `sqlite`: `sqlite3 {R}/db.sqlite .dump`
- `symlink-in-repo`: `cat data/rows.csv`, where `repo/data -> R`
- `case`: `cat {R_upper}/rows.csv` (the casefolded variant)
- `glob-prefix`: `cat {tmp}/mnt/p*/rows.csv`
- `glob-ancestor`: `ls {tmp}/mnt/*/`
- `cd-chain`: `cd {tmp}/mnt && cat phi/rows.csv`
- `heredoc`: `python - <<'EOF'\nopen("{R}/rows.csv")\nEOF`
- `unknown-var`: `cat "$DATA_DIR/rows.csv"`
- `subst`: `cat $(echo {tmp})/mnt/phi/rows.csv`
- `assign-home`: `HOME={tmp}/mnt cat ~/phi/rows.csv`
- `cdpath`: `CDPATH={tmp}/mnt cd phi`
- `for-loop`: `for f in {R}/*.csv; do head -1 "$f"; done`
- `eval-basename`: `eval "cat $(printf %s ph)i/rows.csv"`
- `pipe-sh`: `echo "cat ../mnt/phi/rows.csv" | sh`
- `grep-r-ancestor`: `grep -r x {tmp}/mnt`
- `find-ancestor`: `find {tmp} -name '*.csv'`
- `grep-R-link`: `grep -R x .` (follows `repo/data`)
- `zip-link`: `zip -r out.zip .`
- `python-glob-link`: `python -c "import glob; glob.glob('**', recursive=True)"`
- `rg-L-link`: `rg -L x`
- `nested-claude`: `claude -p hi`
- `nested-codex`: `codex exec x`
- `copier`: `copier update --defaults`
- `guard-file`: `sed -i s/true/false/ brain/.labbrain/config.yaml`
- `plugin-root`: `cp x.py {plugin_root}/labbrain/hooks/guard.py`, with `CLAUDE_PLUGIN_ROOT` set
- `plugin-root-dest`: `cp x.py {plugin_root}`

Rows that must allow:
- `script`: `python train.py --config configs/a.yaml`
- `ls-parent`: `ls {tmp}/mnt`
- `git-status`: `git status`
- `labbrain`: `uvx --from "{plugin_root}" labbrain lint`
- `grep-r-link-nofollow`: `grep -r x .`
- `rg-link-nofollow`: `rg x`
- `echo-path-var`: `echo $PATH`
- `special-params`: `echo $? $#`

A second scope, `GITIGNORED`, has a real data dir `repo/data` (a root) listed in `repo/.gitignore`. Its rows:
- `rg-ignored` (allow): `rg x`
- `grep-r-ignored` (deny): `grep -r x .`
- `rg-u` (deny): `rg -u x`

Also:
- `test_unprotected_scope_allows_all_rows`.
- `test_bash_messages_never_leak`: for every deny row, `message` contains neither the command text nor `rows.csv`.

`tests/test_hook_exposure.py`:
- `test_finds_link_into_root`, `test_ignores_links_elsewhere`, `test_skips_git_and_venv`
- `test_truncated_at_limit`: monkeypatch `WALK_LIMIT=5`.
- `test_cache_hit_skips_walk`: monkeypatch `os.scandir` to raise on the second call; the result is still returned.
- `test_corrupt_cache_ignored`
- `test_session_id_is_hashed_in_filename`: `session_id="../../x"` stays inside `cache_dir/exposure/`.

- [ ] **Step 2: Run, expect failures.** `uv run pytest tests/test_hook_bash.py tests/test_hook_exposure.py -q`
- [ ] **Step 3: Implement.**
  - Lexing: `shlex.shlex(command, posix=True, punctuation_chars=True)` with `whitespace_split=True`. On `ValueError`, use the fallback split and mark the command unconfident.
  - Candidates come from the lexed words plus the raw-text regex ``[^\s'"`()<>;|&=,]*[/~.][^\s'"`()<>;|&=,]*``.
  - Inline assignments, for-loop bindings and `cd`/`pushd`/`-C`/`--directory` bases are as in §5.
- [ ] **Step 4: Run the tests, expect PASS;** then `uv run pytest -q` and ruff.
- [ ] **Step 5: Commit** — `feat(hooks): Bash data guard and link exposure walk`

---

### Task 4: Shared frozen policy, frozen-file guard, PHI pre-scan

**Owns:**
- Create: `labbrain/frozen.py`, with `Policy`, `POLICIES`, `frozen_at_base` (from `_frozen_at_base`), `compare` (from `_compare`), `DoneProtocolsAtBase` (from `_DoneProtocolsAtBase`) and the label helpers, moved verbatim and renamed public.
- Modify: `labbrain/lint/rules/frozen_rules.py` (import from `labbrain.frozen`; rule behaviour unchanged), `labbrain/hooks/writes.py`, `labbrain/phi.py` (only if needed for the new-file scan, see Step 3).
- Test: `tests/test_hook_writes.py`. `tests/test_frozen.py` must keep passing, unchanged.

**Interfaces:**
- Consumes: `Payload`, `Denial`, `Scope`, `scope.vault_of` (Task 1); `gitutil.open_repo`, `resolve_ref`, `ls_tree`, `read_blobs`; `notes.parse_note_text`, `decode_note`; `phi.ScanSettings`, `load_allowlist`, `scan`.
- Produces: `check_write(payload: Payload, scope: Scope) -> Denial | None`, and `labbrain.frozen` as listed.

**Behaviour:** §6 and §7 (pre-write PHI).
- Applies to Write, Edit, MultiEdit and NotebookEdit whose target has `vault_of(target)`.
- The vault-relative path is in true case: walk the components, matching `os.listdir` entries by `fold`. Case-insensitive comparisons for `raw/`, `manuscripts/`, `manuscripts/_proposals/` and `is_note_rel` (applied to the true-case path, with a casefold fallback).
- **Frozen denial** (rule `frozen-file`): `lab-brain frozen-file guard: {rel} is a frozen {type}; this edit is not allowed: {messages}. Supersede the note instead, or change only the allowed fields.` `{messages}` is the `compare` finding messages joined with `; `.
- **Manuscripts denial:** `lab-brain frozen-file guard: manuscripts are edited through proposals; write under manuscripts/_proposals/ instead.`
- **Raw denial:** `lab-brain frozen-file guard: raw/ files are immutable once written; add a new file instead.`
- **Cannot compute an edit on a guarded target:** `lab-brain frozen-file guard: could not apply this edit to a protected file; re-read the file and retry.`
- **PHI denial** (rule `phi`, protected target vault only, file in `in_scan_scope`): `lab-brain PHI guard: the proposed content of {rel} matched {rules} (lines {lines}). Remove individual-level data before writing.`
  - `{rules}` and `{lines}` are the rule names and line numbers only.
  - Allowlisted lines do not count.

- [ ] **Step 1: Failing tests** in `tests/test_hook_writes.py`, using a committed vault from the `vault_dir` fixture style plus `note_text`:
  - `test_done_experiment_body_rewrite_denied`, `test_done_experiment_append_allowed`, `test_done_experiment_status_to_superseded_allowed`, `test_done_experiment_field_change_denied`
  - `test_disallowed_status_transition_denied`
  - `test_handoff_committed_frozen_on_existence`, `test_uncommitted_new_handoff_editable` (the skills' flow: `labbrain new` and then an Edit to `session_goal` is allowed)
  - `test_protocol_referenced_by_done_experiment_frozen`
  - `test_edit_old_string_missing_on_frozen_denied`, `test_edit_old_string_missing_elsewhere_allowed`
  - `test_replace_all_applied`, `test_multiedit_sequence_applied`
  - `test_manuscripts_outside_proposals_denied`, `test_manuscripts_proposals_allowed`
  - `test_raw_existing_denied`, `test_raw_new_allowed`
  - `test_miscased_paths_guarded`: `Experiments/<done id>.md`, `RAW/x`, `Manuscripts/x.md`. Use `pytest.mark.skipif` when the tmp filesystem is case-sensitive for the on-disk part; always test the fold logic.
  - `test_no_git_nothing_frozen`
  - `test_frozen_unparseable_denied`
  - `test_phi_prescan_existing_note_denied`, `test_phi_prescan_new_file` (Review Focus 3), `test_phi_allowlisted_line_allowed`, `test_phi_unprotected_vault_skipped`
  - `test_write_messages_never_leak`: no frontmatter value (other than IDs) and no PHI sentinel appears in any message.
- [ ] **Step 2: Run, expect failures.** `uv run pytest tests/test_hook_writes.py -q`
- [ ] **Step 3: Implement.**
  - Move the shared pieces into `labbrain/frozen.py` first and run `uv run pytest tests/test_frozen.py -q` (it must pass unchanged).
  - Then write `check_write`. HEAD lookup is by rel path, then by stem among HEAD note files.
  - For the PHI pre-scan of a file that does not exist yet: if `phi.scan(..., texts={target: proposed})` skips non-existent paths, add the smallest change to `scan` that lets an entry in `texts` be scanned without existing on disk, with a unit test in `tests/test_hook_writes.py`.
- [ ] **Step 4: Run the tests, expect PASS;** then `uv run pytest -q` and ruff.
- [ ] **Step 5: Commit** — `feat(hooks): frozen-file guard and PHI pre-write scan; share frozen policy with lint`

---

### Task 5: Post-write validator and session start

**Owns:** `labbrain/hooks/post.py`, `labbrain/hooks/session.py`, `tests/test_hook_post.py`, `tests/test_hook_session.py`.

**Interfaces:**
- Consumes: `Payload`, `scope.vault_of`, `scope.find_vault_roots` (Task 1); `validate.validate_path(path, vault=root)`; `findings.render(findings, "text")`, `ERROR`; `vault.load_config`, `Vault.load`, `version_warning`; `index.write`; `lint.run`; `brief.build_brief`.
- Produces: `post_tool_use(payload, env) -> tuple[int, str]` and `session_start(payload, env) -> tuple[int, str, str]`.

**Behaviour:**
- **post-tool-use** (§7):
  - Applies to Write, Edit, MultiEdit and NotebookEdit. `target = file_path or notebook_path`.
  - `root = vault_of(target)`. No vault: `(0, "")`.
  - `findings = validate_path(target, vault=root)`, always passing the containing root explicitly.
  - Any ERROR gives `(2, "lab-brain validator: fix these before continuing:\n" + render(errors, "text"))`. Otherwise `(0, "")`.
- **session-start** (§8):
  - `roots = find_vault_roots(payload.cwd, env)`. None: `(0, "", "")`.
  - For the first root: `load_config`. On failure, return `(0, "lab-brain: vault config error; ask the user to fix .labbrain/config.yaml (`labbrain lint` shows the problem)\n", "")`.
  - Then `Vault.load`, `index.write(vault)`, and stdout `build_brief(vault, lint.run(vault), short=True, warning=version_warning(config))`.
  - If `index.write` fails, the brief is still printed, with a final line `index.md could not be regenerated`.

- [ ] **Step 1: Failing tests**
  - `tests/test_hook_post.py`:
    - `test_schema_error_reported_exit_2`: a note missing a required field. The code is 2, and stderr names the rule and file but not the field values.
    - `test_clean_write_silent`, `test_warning_only_silent`, `test_outside_vault_silent`
    - `test_phi_in_written_note_reported` (protected vault)
    - `test_labbrain_vault_env_does_not_redirect`: `LABBRAIN_VAULT` points at another vault. The target's own vault is validated.
  - `tests/test_hook_session.py`:
    - `test_no_vault_silent`
    - `test_brief_printed_and_index_regenerated`: stdout has at most 4 lines; `index.md` exists and matches `index.render`.
    - `test_version_warning_line`
    - `test_broken_config_one_line`
    - `test_short_brief_under_3s_on_300_notes`: `pytest.mark.slow`, a protected vault of 300 generated notes, asserting under 3.0 s.
    - `test_subfolder_env_relative_vault`: `LABBRAIN_VAULT="brain"` with `CLAUDE_PROJECT_DIR` set.
- [ ] **Step 2: Run, expect failures.** `uv run pytest tests/test_hook_post.py tests/test_hook_session.py -q`
- [ ] **Step 3: Implement.** If the 300-note timing fails, add the §8 fast-check fallback (skip git-based rules in the short brief, with the count labelled `(fast check)`). Otherwise leave `brief` unchanged.
- [ ] **Step 4: Run the tests, expect PASS;** then `uv run pytest -q` and ruff.
- [ ] **Step 5: Commit** — `feat(hooks): post-write validator and session-start brief`

---

### Task 6: Integration, performance, docs, end-to-end gate, release prep

**Files:**
- Create: `tests/test_hook_integration.py`, `tests/smoke/test_smoke_hooks.py`, `scripts/m5-gate.sh`, `docs/decisions/ADR-20261020-hooks.md`.
- Modify:
  - `pyproject.toml`, `labbrain/__init__.py`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`: version `0.3.0`;
  - `uv.lock` (`uv lock`);
  - `CHANGELOG.md` (`## 0.3.0 (unreleased)`);
  - `README.md` (a Hooks section).

**Steps:**
- [ ] **Step 1: Integration tests** in `tests/test_hook_integration.py`, run through `run_hook` (or the CLI subprocess where stated):
  - `test_corpus_through_entry`: every Task 3 deny row as a Bash payload gives exit 2; every allow row gives exit 0. Plus Read, Write and Edit fixtures for the Task 2 cases.
  - `test_no_output_ever_has_permission_decision`: across all corpus runs, stdout is either empty or (for session-start) plain text, and never parses as JSON containing `permissionDecision`.
  - `test_sentinels_never_in_any_output`: sentinels planted in data file contents and in a data file name. Concatenated stdout and stderr across all runs contain neither.
  - `test_warm_latency_budget` (`slow`): the CLI subprocess `python -m labbrain hook pre-tool-use`, median of 5 runs after one warm-up:
    - ≤ 450 ms with no vault (3× the 150 ms engine budget);
    - ≤ 900 ms on a Read in a protected vault (3× 300 ms).
  - `test_hooks_json_commands_fail_closed`: run each PreToolUse command string from `hooks/hooks.json` through `sh -c` with `CLAUDE_PLUGIN_ROOT=/nonexistent` and `PATH` limited to `/usr/bin:/bin`. The exit code is 2.
- [ ] **Step 2: End-to-end smoke** `tests/smoke/test_smoke_hooks.py` (`pytest.mark.smoke`, same harness and skip rules as `tests/smoke/conftest.py`):
  - Build a protected vault (`make_vault` with `protected_data: true` and a `data_paths` entry for `<tmp>/phi`, holding `rows.csv` with a `secrets.token_hex` sentinel). `git init` and commit. Run `claude -p` with `--plugin-dir <repo root>`.
  - `test_read_of_data_blocked`: the prompt asks the agent to show `<tmp>/phi/rows.csv` with the Read tool, then with `cat`. Assert the sentinel is absent from the result text and from the transcript, and that the transcript shows hook blocks.
  - `test_frozen_body_edit_blocked`: the prompt asks it to rewrite the body of a committed done experiment. Assert the file is unchanged.
  - `scripts/m5-gate.sh` runs these with `UV_NO_CACHE=1`, as `scripts/m4-gate.sh` does.
- [ ] **Step 3: Docs.**
  - **README "Hooks" section:**
    - the four hooks;
    - fail-closed behaviour;
    - `uv` required;
    - CLI ≥ 2.1.295 recommended for `onFailure`;
    - what the user, not the agent, changes;
    - that data paths go in config files, not commands;
    - the residual risks of §12;
    - the DUA/IRB statement.
  - **ADR** recording:
    - the §3 facts with the CLI version;
    - the decisions of §13;
    - the M5 gate run (filled in when it runs);
    - the dated decision that hooks live in the plugin.
  - **CHANGELOG** entry.
  - Version bump in all four files. `tests/test_plugin_manifest.py::test_manifests_agree_with_pyproject` must pass.
- [ ] **Step 4: Verify.** Stage everything. Run `uv run pytest -q`, `uv run pytest -m slow -q`, `uv run ruff check .` and `uv run ruff format --check .`. Then `claude plugin validate . --strict` with the bundled CLI at `/private/tmp/claude-501/smoke-bin/claude`.
- [ ] **Step 5: Commit** — `feat(hooks): integration tests, end-to-end gate and docs for 0.3.0`

Release (controller, with the user's approval at each outward step):
1. Run the smoke tests and the gate; record them in the ADR.
2. Date the CHANGELOG.
3. Push and open the PR.
4. Merge with `--match-head-commit <full sha>`.
5. Tag `v0.3.0`.

---

### Task 7 (Phase B): Template v0.3.0

**Repo:** `/Users/jbotas/Documents/lab-brain-template`, branch `feat/v0.3.0`, in a worktree outside the repo directory.

**Files:**
- Modify: `copier.yml` (`engine_version` default `0.3.0`), `pyproject.toml` and `uv.lock` (labbrain `0.3.0`), `template/README.md.jinja`, `template/CLAUDE.md.jinja`, `CHANGELOG.md`.
- Test: `tests/test_docs.py`, `tests/test_settings.py`.

- [ ] **Step 1: Failing tests:**
  - `test_settings.py`: the rendered plugin ref is `v0.3.0`.
  - `test_docs.py`:
    - the rendered README has a "Guardrails" section mentioning `uv`, the plugin, "do not replace" with DUA and IRB, and config files for data paths, plus the user-only changes (`.labbrain/`, `.claude/settings`, `copier update`);
    - with `protected_data: false`, the protected-only sentences are absent;
    - `CLAUDE.md` contains: `Hooks enforce these rules: when a call is blocked, change approach instead of retrying.`
- [ ] **Step 2: Run, expect failures.** `uv run pytest -q`
- [ ] **Step 3: Implement.** Bump the version, write the README section (§10), add the `CLAUDE.md` line, and add a CHANGELOG `## 0.3.0 (unreleased)` with an "Upgrading from 0.2.0" note: `copier update` picks up the new plugin ref, and the hooks need `uv`.
- [ ] **Step 4: Run** `uv run pytest -q` (CI-equivalent; needs the `v0.3.0` engine tag).
- [ ] **Step 5: Commit** — `feat: pin engine 0.3.0 and document the guardrail hooks`

Release, with approval: PR, then merge, then tag `v0.3.0`, then a fresh `copier copy` smoke test (the plugin ref is `v0.3.0`, and `lint` reports 0 errors).
