# lab-brain M5: hooks design

Milestone M5 of the lab-brain spec (section 8, "Hooks and protected-data guardrails"). It ships in engine v0.3.0, which is also plugin v0.3.0, and is followed by template v0.3.0.

## 1. Intent

A lab-brain vault is a knowledge base for coding agents. Agents log context, implementations, experiments and results there, and later agents read it to pick up where the earlier ones stopped. Agents write most of the vault, so its rules have to hold without a human watching each write. In projects that touch protected data, individual-level records must never enter an agent's context.

Up to M4 these rules were enforced only after the fact, by lint and pre-commit, plus Claude Code permission rules that match path text. M5 adds Claude Code hooks, so that a breaking tool call is stopped or corrected while the agent works:

| Hook | Event | Job |
| --- | --- | --- |
| Data guard | PreToolUse | Block any tool call that would read a protected data path |
| Frozen-file guard | PreToolUse | Block edits that rewrite frozen notes, `raw/` files or manuscripts |
| Write validator | PreToolUse + PostToolUse | Block PHI before it is written; report schema errors after each write |
| Session brief | SessionStart | Give the agent a short vault orientation and any engine-version warning |

The guardrails make the safe path the default. They do not replace the institution's DUA, IRB or security rules, and the template README must say so (section 10).

## 2. Goals, non-goals, anti-goals

**Goals**

- A protected vault blocks a data-path read end to end, through Read, Bash (`cat`, `head`, `python -c`, `duckdb` and others), symlinks, `..`, `~`, globs and changes of directory.
- Agents get frozen-note and PHI errors at the moment of the write, phrased so they can fix them.
- Each session starts with the agent oriented: the brief, plus a fresh `index.md`.
- Hook latency stays low enough to run on every tool call.

**Non-goals**

- **Paths the command text never shows.** A script that opens a data file runs normally. Running analysis code over protected data is the point of an ML project, and its output is aggregate. The rule that individual-level records stay out of context is what `CLAUDE.md` tells the agent. The hook cannot judge what a program prints.
- **Deliberate obfuscation**, such as base64-encoded paths, paths built from string pieces, or a script written and then run. Stopping that needs an OS-level sandbox (section 12).
- **Frozen-note edits made through Bash** (`sed -i`, redirection). The `frozen-edit` lint rule and pre-commit still catch them at commit time.
- **Sessions outside a vault.** They are not guarded: only data paths of the vault in scope are known.

**Anti-goals** (failure even if everything "works")

- **A guard that fails open.** An engine crash, missing `uv`, a broken config or bad JSON must block, never allow.
- **A guard that leaks while blocking.** A block message must never echo the command, a file name under a data path, or file contents. It names the rule and the `data_paths` entry as configured.
- **A hook that ever emits a `permissionDecision` of `allow`.** That would skip the user's own permission prompts. Hooks only deny or stay silent.
- **Noticeable slowness** on everyday tool calls.

## 3. Verified platform facts

Captured on 2026-10-20 with the installed Claude Code 2.1.284, using real hook payloads from a headless run, plus the hooks docs at `code.claude.com/docs/en/hooks`.

- **Payloads.** PreToolUse and PostToolUse send `tool_name`, `tool_input`, `cwd`, `session_id`, `permission_mode`, `transcript_path`, `tool_use_id` and `hook_event_name`. PostToolUse adds `tool_response` and `duration_ms`. SessionStart sends `source`, one of `startup|resume|clear|compact|fork`.
- **`tool_input` per tool:**
  - Read: `{file_path}`, absolute.
  - Write: `{file_path, content}`.
  - Edit: `{file_path, old_string, new_string, replace_all}`.
  - Bash: `{command, description}`.
- **No Grep or Glob tools in 2.1.284.** Asked to grep and glob, the agent used Bash (`grep -r`, `ls *.txt`). Other builds have Grep, with `path`, `glob` and `pattern`, and Glob, with `path` and `pattern`. Both must still be handled.
- **Glob in 2.1.304** (checked at build time). CLI 2.1.304 does have a Glob tool. It runs `rg --files --null --glob <p> --sort=modified --no-ignore --hidden`, with no `--follow`. Claude Code splits an absolute pattern at the first `*?[{`, rewrites overlapping leading components, and resolves `..` textually (Node `path`).
- **Exit codes.** Exit 2 blocks a PreToolUse call and shows stderr to Claude. On PostToolUse, exit 2 shows stderr to Claude. Any other non-zero exit is a non-blocking error: **the tool call proceeds**.
- **Fail-closed form, verified.** A shell-form command `<engine> hook … || exit 2` whose engine is missing blocked both a Bash and a Read call on 2.1.284.
- **`onFailure: "block"`** (CLI 2.1.295 or later) also blocks on timeout and on start failure. On 2.1.284 the key is tolerated: the hook still loaded and ran. Without it, **a timed-out PreToolUse hook lets the call proceed**.
- **Hook decisions.** Hooks run in parallel and deny wins. Plugin hooks merge with settings hooks. Commands without `args` run under `sh -c`.
- **Placeholders.** `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PROJECT_DIR}` are substituted, and both are also set as environment variables.
- **SessionStart output.** Plain stdout on exit 0 is added to Claude's context.
- **The working directory follows `cd`.** A `cd` persists across Bash calls, and the next payload's `cwd` reports it. The hook process itself runs in that cwd. `CLAUDE_PROJECT_DIR` stays at the project root. In this build, a `cd` outside the project is reset to the project root after the call. So the guard needs no per-session cwd state: each call's `cwd` is the cwd the command will run in.
- **Latency.** A warm `uvx --from <plugin root> labbrain --version` takes about 70 ms. Importing `labbrain.vault`, which pulls in pydantic, takes about 100 ms warm. A cold first run takes several seconds.

The builder re-checks these facts against the CLI current at build time and records the payloads as test fixtures (section 11).

## 4. Architecture

**Where the hooks live.** The hooks ship in the plugin, in `hooks/hooks.json` at the repo root next to `skills/`. They are versioned and pinned with the engine, and the template already enables the plugin per project (`enabledPlugins`, and the subfolder snippet does the same). The template's permission deny rules stay as a second layer.

**One engine entry point per event:** `labbrain hook pre-tool-use`, `labbrain hook post-tool-use` and `labbrain hook session-start`.
- Each reads the hook payload JSON from stdin.
- One PreToolUse process runs all the pre-write checks (data guard, frozen-file guard, PHI pre-scan), so a tool call costs one engine start, not three.

```json
{
  "description": "lab-brain guardrails: data guard, frozen-file guard, write validator, session brief",
  "hooks": {
    "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command",
      "command": "uvx --from \"${CLAUDE_PLUGIN_ROOT}\" labbrain hook pre-tool-use || exit 2",
      "timeout": 120, "onFailure": "block"}]}],
    "PostToolUse": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit", "hooks": [{"type": "command",
      "command": "uvx --from \"${CLAUDE_PLUGIN_ROOT}\" labbrain hook post-tool-use || exit 2",
      "timeout": 120}]}],
    "SessionStart": [{"hooks": [{"type": "command",
      "command": "uvx --from \"${CLAUDE_PLUGIN_ROOT}\" labbrain hook session-start",
      "timeout": 60}]}]
  }
}
```

The exact JSON is the builder's, but these properties are fixed:
- The PreToolUse matcher covers every tool.
- PreToolUse and PostToolUse fail closed via `|| exit 2`.
- PreToolUse also sets `onFailure: "block"`.
- Timeouts are generous enough to cover a cold `uvx` start.

**Exit contract of `labbrain hook`**

- **Exit 0:** allow, or nothing to report. Stdout is empty, except for session-start, which prints the brief.
- **Exit 2:** deny (pre) or report (post), with a short sanitized reason on stderr.
- **No other exit code, ever.**
  - Any unexpected exception is caught at the top. Pre-tool-use exits 2 with "lab-brain guard failed; blocked to be safe". Post-tool-use exits 2 with "lab-brain validator failed". Session-start exits 2 with a one-line notice.
  - No traceback is ever printed (a project rule).
- **Malformed or missing stdin JSON** is treated as failure: pre-tool-use denies.

**Vault in scope.** The guard unions the data paths of every vault it can find:
- the vault containing the payload `cwd`;
- the vault containing `$CLAUDE_PROJECT_DIR`;
- `$LABBRAIN_VAULT`. When this is relative, as in subfolder mode, it is resolved against `$CLAUDE_PROJECT_DIR`, not the current cwd, because Bash's cwd moves during a session.

For writes, the frozen-file guard and validator use the vault that contains the target file.

**Failures in a vault's own setup**
- A vault whose config fails to load is treated as protected with unknown data paths.
- The only call allowed is the Read tool on that vault's `.labbrain/` files, so the agent can tell the user what is wrong.
- Every other call is denied, Bash included (`labbrain lint` too), with a message asking the user to fix `.labbrain/config.yaml`. The agent may not edit the file: an agent "fixing" it could switch protection off.
- No vault found anywhere: allow, after a cheap search with no pydantic import.

**Calling `validate_path` from hooks.** The existing `validate_path` prefers `$LABBRAIN_VAULT` over the vault that contains the target, and resolves a relative value against the process cwd. Hooks must therefore find the containing vault themselves and pass it explicitly.

**Performance budget.** A warm PreToolUse call outside a vault or in an unprotected vault takes ≤ 150 ms of engine time. In a protected vault, ≤ 300 ms. A test enforces generous multiples of these so CI does not flake.
- Heavy modules (lint, PHI, frozen rules) are imported only on the paths that need them.
- Config is loaded once per process.

## 5. Data guard

**Active when** the vault in scope has `protected_data: true` and at least one `data_paths` entry.

**Protected roots**
- Each entry is expanded (`~`) and resolved: symlinks, `..`.
- Containment is checked three ways:
  - by canonical path prefix;
  - by `(st_dev, st_ino)` identity of the candidate and each of its parents, as `LocalAdapter._guard` already does;
  - by NFC-normalized, casefolded string comparison.
- The casefold check is a deliberate over-approximation: on a case-sensitive filesystem it blocks `/Data` as well as `/data`. That is an accepted false positive.

**Decision per tool**
- **Session cwd inside a protected root:** deny every tool call.
- **Read, Write, Edit, MultiEdit, NotebookEdit, NotebookRead, and any LS-style tool:** deny when the target path (`file_path`, `notebook_path`, `path`) is inside or equal to a protected root.
  - Writes are covered too: an Edit returns the original file in its response.
- **Grep:**
  - deny when its search root (`path`, default cwd) is inside a protected root;
  - deny when its search root is an ancestor of one (a recursive search would enter it);
  - deny when its `glob` names a protected path.
- **Glob** is a recursive construct (rulings R20, R21). It is denied when a protected root is inside or under any search base. The bases are:
  - `path`, or the cwd;
  - the deepest literal directory before Claude Code's wildcard cut (section 3);
  - and literal runs of the pattern.
  - A component starting with `!`, or any `\`, is denied.
- Glob and Grep also run the link-exposure walk of Bash rule 6b (ruling R10).
- **Two readings of every path** (ruling R22). Every path is judged both physically (symlinks resolved first) and textually (`..` collapsed). Either reading inside a protected root denies.
- **Bash:** see below.
- **Known tools that carry no file paths** (Agent/Task, TodoWrite, ToolSearch, Skill, AskUserQuestion, WebSearch and the like): skipped. The list is explicit, and subagents' own tool calls are hooked anyway.
- **Every other tool, including `mcp__*`:** every string value in `tool_input` (walked recursively, size-capped) is a path candidate:
  - absolute and `~` candidates are resolved directly;
  - relative candidates are resolved against cwd;
  - plus the textual net below.

**Bash rules.** All rules over-approximate. Any rule firing denies.

1. **Candidates.**
   - Lex the command with a shell-aware lexer. If lexing fails, fall back to splitting on whitespace and shell metacharacters.
   - Candidates are:
     - every word;
     - every path-like substring of the raw command text (runs containing `/` or starting with `~` or `.`);
     - the path-like pieces of each token split on `: [ ] { } @ ! $ % ^ * + ?` (ruling R17), so `file:../x` and `[../x]` count. The extra split applies only to text with no wildcard, so rules 2 and 5 still see the whole token. MCP strings get the same split.
   - Scanning the raw text also covers heredoc bodies and the code inside `python -c`, `node -e`, `duckdb -c` and similar.
2. **Expansion.**
   - Expand `~`, `~user`, `$HOME`/`${HOME}`, and variables assigned earlier in the same command (`X=/p; cat $X/f`).
   - Expand other variables from the hook's environment.
   - A for-loop variable stands for the loop's words, which are candidates in their own right.
   - Special and positional parameters (`$?`, `$#`, `$$`, `$!`, `$0`–`$9`, `$@`, `$*`) standing alone are not paths and are ignored. Next to path text (`p$1hi`, `../mnt/p$@hi`) they are wildcards (ruling R27). Their marks survive binding into variables and loop lists and are resolved where the value is used (ruling R29).
   - **Wildcards.** A variable that cannot be bound to a value, a command substitution (`$(…)` or backticks), or a glob character makes that part of the candidate a wildcard.
   - **Literal substitutions** (rulings R19b–R19e). The one substitution read as literal text is a whole word `"$(cat <<'EOF' … EOF)"` with a quoted delimiter, which is how commit messages and PR bodies are passed. It is literal only when:
     - every program word in the command is exactly `git` or `gh`, running built-in subcommands: no `push`, `fetch` or `pull`, not `gh repo` or `gh gist`, and no `--` after `gh`;
     - the command has no assignments and no carriage return;
     - its parentheses are balanced;
     - the literal is not in program position;
     - and nothing in the command redefines programs (aliases, functions, shell-state builtins).
     Every other substitution, including `echo` and `printf` forms, stays a wildcard.
     - A candidate whose first component is a wildcard (`$DATA_DIR/f`, `$(…)/f`) could point anywhere, so **deny**.
     - The hook's environment is not the Bash tool's environment (the Bash tool loads the user's shell profile), so an unknown variable must not be read as harmless.
   - Deny a command that assigns `HOME`, `CDPATH`, `PWD` or `OLDPWD`.
3. **Resolution bases.**
   - A relative candidate is resolved against the payload cwd.
   - It is also resolved against every directory the command could change into: arguments of `cd` and `pushd`, `-C` and `--directory`-style options, and other candidates naming existing directories.
   - So `cd /x && cat data/f` is caught without modelling control flow.
4. **Inside.** Deny when any resolved candidate is inside or equal to a protected root.
5. **Wildcards.** For a candidate with a wildcard part:
   - deny when its literal prefix is inside a protected root, or is an ancestor of one;
   - also expand real globs against the filesystem and check each match.
6. **Recursion.** A recursion start is a directory candidate, or the cwd for a program with an implicit path. Recursive constructs are:
   - `grep`/`egrep` with `-r`, `-R` or `--recursive`;
   - `rg`, `ag`, `ack`, `find`, `fd`, `tree`, `du`, `ls -R`, `tar`, `zip`, `rsync`, `scp -r`;
   - `cp` with `-r`, `-R` or `-a`;
   - `git grep`;
   - inline-code interpreters (`python -c`, `node -e`, `perl -e`, `ruby -e`, `Rscript -e`, `duckdb`, `sqlite3`).

   A plain `ls` of the parent, which shows only names one level down, is allowed.

   - **(a) A protected root lies under a recursion start.** The root is a real directory strictly below the start. Deny any recursive construct.
     - Exception: `rg` is allowed when every such root is ignored by git (`git check-ignore`) and the command has no flag that disables ignores or follows links (`-u`, `--no-ignore*`, `-L`, `--follow`).
     - The reason is that this CLI's agents search through Bash, and in subfolder mode the code repo root may hold a gitignored data folder.
   - **(b) A link into a protected root lies under a recursion start.** The guard finds such links with a bounded walk:
     - The walk does not follow links. It skips `.git`, virtual environments, `node_modules` and the protected roots. It is cached per session, and per start directory, under `${CLAUDE_PLUGIN_DATA}`.
     - When a link is found, deny link-following constructs:
       - GNU `grep -R`/`--dereference-recursive`, BSD `grep -S`;
       - `rg -L`/`--follow`, `find -L`/`-H`/`-follow`, `fd -L`/`--follow`, `tree -l`, `du -L`;
       - `cp -L`/`-H`, `rsync -L`/`-k`/`--copy-links`, `tar -h`/`--dereference`;
       - `zip`, which follows links by default unless given `-y`;
       - every inline-code interpreter, whose code may follow links (`glob.glob(…, recursive=True)` does).
     - A walk cut short by its bound denies every recursive construct from that start.
     - Links created later by a command that names the data path are already blocked. Links created by programs are the non-goal of section 2.
   - The builder keeps the program and flag lists in one place.
7. **Textual net.** Deny when the raw command text contains a protected root's spelling, compared casefolded:
   - as configured;
   - `~`-expanded;
   - or canonical.
8. **Unconfident commands.** Unconfident means:
   - lexing failed;
   - or the command contains `eval`, `exec`, `source`/`.`, `xargs`, a pipe into `sh`/`bash`/`zsh`, or `base64`.
   - For these, also deny when a protected root's final component appears as a delimited word in the text. The check also runs on the text with quote characters and backslashes removed (ruling R26), so `p""hi` and `p\hi` count. Per the spec, the message asks the agent to have the user run the command themselves.
   - Unknown variables and command substitutions are handled by rule 2.
9. **Lexing details.**
   - Redirection targets never name programs, scripts or `cd` targets (fix round 5).
   - `<<<` is a herestring, not a heredoc (ruling R24).
   - `$"…"` is a quoted string (ruling R24).

**Grep and Glob tools.**
- Grep is treated as `rg` (rule 6a, without the ignore exception, since the tool's flags are not visible).
- Glob is a recursive construct, with the search bases above.
- Both also run the link-exposure walk (rule 6b, ruling R10).

**Guard self-protection** (protected vaults only). An agent that can edit the guard's configuration can switch the guard off. A prompt injection could ask for exactly that. So:
- **File tools may not write these guard files:**
  - `.labbrain/**` and `.copier-answers.yml` of the vault in scope;
  - `.claude/settings.json` and `.claude/settings.local.json` under the vault, under `$CLAUDE_PROJECT_DIR`, and under `~/.claude/`;
  - the guard's own code and caches: `${CLAUDE_PLUGIN_ROOT}/**`, `~/.claude/plugins/**` (which also holds `${CLAUDE_PLUGIN_DATA}`), and the uv cache directory.
    - These matter because `uvx --from` rebuilds the engine when its sources change.
- **MCP tools** may not name guard files either (ruling R11). Paths embedded in longer MCP strings are candidates too (R12), and a string over the size cap denies (R13).
- **Bash commands are denied when they:**
  - name a guard file, or `mv`, `rm` or `ln` an ancestor of one (ruling R7);
  - run `copier`;
  - or start a nested agent CLI: `claude`, or any program named in the vault config's `agents` list (author names that double as CLI names; the default is `claude`, `codex`, `gemini`).
    - A nested agent can run without these hooks (`claude -p --settings '{"disableAllHooks":true}'`).
- Reading guard files with the Read tool stays allowed.
- A vault whose config fails to load allows only the Read tool on its `.labbrain/` files (section 4).
- The user makes these changes themselves, and the README says so.

**Messages.** For example: `lab-brain data guard: this Bash command refers to protected data path #1 ('<entry as configured>'). Individual-level data must not enter the session. If you need this run, ask the user to run it themselves and share only aggregate results.` A message never includes the command, the candidate path or any file contents.

## 6. Frozen-file guard

**Runs** in the same PreToolUse process for Write, Edit, MultiEdit and NotebookEdit, when the target is inside a vault (the target's vault). Active in every vault, protected or not.

**Proposed content**
- Write: `content`.
- Edit: `old_string` → `new_string` applied to the current file, all occurrences if `replace_all`, else the first.
- MultiEdit: its edits in order.
- **Edit cannot be computed** (`old_string` not found, or the file unreadable):
  - deny when the target is a frozen note, an existing `raw/` file, or under `manuscripts/` outside `_proposals/`, with "re-read the file and retry";
  - otherwise allow, since the tool will fail.
  - Denying the guarded cases avoids betting that the Edit tool matches text the same way the guard does.

**Paths and case.**
- The path relative to the vault is computed in its true on-disk case, by matching directory entries.
- `raw/`, `manuscripts/`, `_proposals/` and the note folders are compared casefolded.
- Otherwise `Experiments/…` or `RAW/…` would slip past on case-insensitive APFS.

**Rules**
1. **Manuscripts.** Deny any write under `manuscripts/` outside `manuscripts/_proposals/`, including new files.
2. **Raw files.** Deny modification of any `raw/` file that already exists on disk. A new file under `raw/` is allowed: that is ingest. This is stricter than lint, and matches the template's `Edit(/raw/**)` deny rule.
3. **Frozen notes.**
   - A note is frozen when its committed version (git `HEAD`) is frozen under `POLICIES`, which now lives in `labbrain/frozen.py`:
     - a frozen status;
     - a type frozen on existence (`idea`, `handoff`, `dataset`);
     - or a protocol referenced by a done experiment at HEAD.
   - The proposed content is compared with that HEAD version using lint's `frozen-edit` comparison (`_compare`): mutable fields only, allowed status transitions, body insertions only. So the guard enforces exactly what lint would report at commit.
   - Deny on any finding, listing the finding messages. They are already value-free.
   - The shared pieces (`POLICIES`, `frozen_at_base`, `compare`) live in `labbrain/frozen.py`, which the lint rule and the guard both use.
4. **Proposed content does not parse.** On a frozen note, deny ("frozen note no longer parses"). On a non-frozen note, allow: the post-write validator reports it.

**Baseline is git HEAD, as in lint.**
- A note created or recorded in this session stays editable until it is committed. `brain-core` promises exactly that, and the skills rely on it: the handoff, idea, decide and exp-log steps edit a note right after `labbrain new` or `exp record` writes it.
- The HEAD blob is found by path, and by ID for a moved note, as in lint.
- No repository, or no commits: nothing is frozen, as in lint.

## 7. Write validator

- **Pre-write PHI block** (PreToolUse, protected vaults, files in PHI scan scope):
  - scan the proposed content with `phi.scan_text`, using the vault's settings, plus the vault's line-hash allowlist;
  - deny on any hit, reporting rule names and line numbers only.
  - *My call, beyond spec section 8,* which runs the scan only after the write: blocking first means PHI never lands on disk. The post-write scan below still runs.
- **Post-write validation** (PostToolUse, Write, Edit, MultiEdit and NotebookEdit inside a vault):
  - run `validate_path` on the written file: schema, duplicate IDs, and the PHI scan when protected;
  - errors exit 2 with the findings on stderr, so Claude fixes them;
  - warnings only, or a clean file: exit 0 and stay silent;
  - files outside a vault: exit 0 silently.
- **No schema check before writing**: an agent may write a note in several edits, and the in-between states may not be valid.

## 8. Session brief

On every SessionStart source, `labbrain hook session-start`:
1. Finds the vault. With no vault, it prints nothing and exits 0.
2. Regenerates `index.md`, as spec section 10 requires.
3. Prints `labbrain brief --short`: at most four lines, including the engine-version warning.
   - Note titles pass through `findings.sanitize`, so PHI-shaped text in a title is redacted (ruling R8).
   - If `index.md` cannot be regenerated, the counts line says so (" · index.md not regenerated"), keeping the brief at four lines (ruling R9).

**Errors**
- A vault config that fails to load prints one line, "lab-brain: vault config error; ask the user to fix .labbrain/config.yaml (`labbrain lint` shows the problem)", and exits 0. The guard blocks other calls until it is fixed (section 4).
- An unexpected failure exits 2 with a one-line notice. The session always proceeds.

**Lint cost.** `brief` runs the full lint; the plugin backlog flags this for M5.
- The short brief must finish within 3 s on a 300-note protected vault.
- If it does not, the builder may skip git-based rules in `--short`, saying so in the count ("Lint errors N (fast check)").

## 9. Data flow summary

```
tool call ──► PreToolUse: labbrain hook pre-tool-use
                 ├─ data guard          (protected vault in scope)
                 ├─ guard self-protection (protected vault in scope)
                 ├─ frozen-file guard   (Write/Edit into a vault)
                 └─ PHI pre-scan        (Write/Edit into a protected vault)
              any deny → exit 2 → call blocked, reason shown to Claude
tool runs
         ──► PostToolUse (writes): labbrain hook post-tool-use → validate_path
              errors → exit 2 → Claude sees findings and fixes them
session start ──► labbrain hook session-start → index + brief --short → context
```

## 10. Template v0.3.0 follow-up

A separate small PR in `lab-brain-template`, as in M4:
- Pin engine 0.3.0. The plugin ref moves to `v0.3.0`.
- Add a README section on guardrails:
  - what each hook does;
  - that hooks need the plugin enabled and `uv` on `PATH`;
  - that the user, not the agent, edits `.labbrain/` and `.claude/settings*.json` and runs `copier update`;
  - the statement that the guardrails do not replace the institution's DUA, IRB or security rules;
  - that analysis code should take data paths from config files, because a command naming a data path is blocked.
- Add a `CLAUDE.md` line: hooks enforce these rules, so a blocked call means change approach, not retry.

## 11. Testing and gate

- **Payload fixtures.** Real payloads recorded from the current CLI (Read, Write, Edit, Bash, SessionStart, PostToolUse) are stored as JSON under `tests/fixtures/hooks/`, with paths templated. Every hook test feeds `labbrain hook …` such payloads on stdin and asserts on the exit code and stderr.
- **Data-guard corpus.** Table-driven allowed/blocked Bash commands. It covers at least:
  - `cat`, `head`, `less`, `wc` and `python -c` with `open(…)`, plus `duckdb -c "select * from '…'"`, `sqlite3`;
  - absolute, `~`, `$HOME` and relative forms, `..` escapes, and a symlink in the vault pointing into a data root;
  - a differently cased path, globs (`/x/da*/f`), and `cd /x && cat data/f`;
  - `grep -r` from an ancestor, `find`, heredocs, `eval`, and a pipe into `sh`;
  - allowed controls: `python train.py --config c.yaml`, `ls` of the parent, `labbrain lint`, `git status`, and commands in an unprotected vault.
  - Unbindable variables: `cat "$DATA_DIR/f"` and `$(…)/f`. Inline `HOME=`/`CDPATH=` assignments. A for-loop over a data glob.
  - A link to a data root inside the repo, reached with `grep -R`, `zip -r`, `python -c` using a recursive glob, and `rg -L`. Plus allowed controls: `grep -r` and `rg` over the same tree.
  - A gitignored data folder under the repo, searched with `rg` (allowed) and with `grep -r` or `rg -u` (denied).
  - A truncated walk.
  - Nested `claude -p`, a write into the plugin root, `copier update`.
  - Plus Read, Grep and Glob payloads, an MCP payload with a data path in a nested argument, and fail-closed cases: bad JSON, broken config (only the Read tool on `.labbrain/` is allowed), and an engine exception.
- **Leak tests.**
  - Plant sentinel strings in data files and data file names. Assert that no hook output (stdout or stderr), for any corpus entry, contains a sentinel or the command text.
  - Assert that hook stdout never carries a `permissionDecision`. Frozen messages legitimately use the word "allowed", so the check is on the JSON field, not the word.
- **Frozen-guard tests.** Per policy:
  - allowed field edits, a forbidden field edit, a body rewrite against an append, a disallowed status transition;
  - an uncommitted fresh note edited freely, which is the skills' flow;
  - an Edit whose `old_string` is missing, on a frozen note;
  - mis-cased `Experiments/`, `RAW/` and `Manuscripts/` paths;
  - manuscripts inside and outside `_proposals/`, and a new versus an existing `raw/` file.
- **Validator tests.** Schema error reported (exit 2), clean write silent, PHI pre-write block, file outside the vault.
- **Session tests.** No vault, normal vault, version warning, broken config, and the 300-note timing.
- **`hooks.json` test.** It parses; matchers and commands are as in section 4; `|| exit 2` sits on the pre and post commands; `claude plugin validate . --strict` still passes in CI.
- **End-to-end gate** (opt-in smoke test, like M4's).
  - Generate a protected vault from the template with a data path holding a sentinel file. Load the plugin with `--plugin-dir`, and ask `claude -p` to show the sentinel file's contents via Read and then via Bash.
  - Assert both calls were blocked and the sentinel never appears in the output or the transcript.
  - Then ask for an edit to a frozen note's body and assert it was blocked.
  - Record the run in a new ADR.

## 12. Residual risks (documented, not fixed)

- **Code that reads data and prints records** (by design, section 2), and obfuscated paths. The stronger fix is Claude Code's OS-level Bash sandbox with data paths denied for reading. That would also block legitimate training runs, so it is the user's per-project choice. It is noted in the README as an option and not built in M5.
- **CLI older than 2.1.295:** a PreToolUse hook that times out lets the call proceed. Mitigated by the 120 s timeout and fast hooks, and closed on newer CLIs by `onFailure`.
- **Hard links** to individual files inside a protected root are not detected, as with the M4 tracker guard.
- **The plugin must be enabled and `uv` installed.** If `uv` is missing, every tool call in a session with the plugin enabled is blocked. That is loud, but it fails closed.
- **Bash writes to frozen notes** are caught only at lint or commit.
- **MCP tools that write vault files** bypass the frozen-file guard, the PHI pre-scan and the post-write validator (ruling R14). Lint and pre-commit catch them at commit.
- **Percent-encoded or `file://` URL spellings** of a data path are not decoded (ruling R16).
- **`RIPGREP_CONFIG_PATH`** could add `--follow` to `rg`. The link-exposure walk mitigates it.
- **`git -C` or `--git-dir` with a pre-written repository config** can run code.
- **Paths built by concatenation or encoding inside inline code**, when no link into a root sits under the cwd.

## 13. Decided here vs left to the builder

**Decided**

- Hooks ship in the plugin, with one engine entry point per event.
- Fail closed everywhere on the pre path, and never emit `allow`.
- The vault-in-scope union rule, and relative `LABBRAIN_VAULT` resolved against the project dir.
- A broken config allows only the Read tool on `.labbrain/`.
- The Bash over-approximation rules 1–8, with unbindable leading variables denied, the link-exposure walk and the `rg` gitignore exception.
- Guard self-protection, covering config, settings, plugin code and caches, and nested agent CLIs.
- The message format.
- The frozen baseline is git HEAD, as in lint; guarded Edits that cannot be computed are denied; paths are casefolded.
- The PHI pre-write block, and no schema check before writing.
- Index regeneration and the brief at SessionStart.
- Template v0.3.0 as a follow-up PR.

**Left to the builder**

- The exact lexer and candidate regex.
- The exact skip-list of non-file tools and the recursive-program list.
- Module layout. Suggested: a `labbrain/hooks/` package with `guard.py`, `bash.py`, `frozen.py` and `entry.py`, plus a shared frozen-policy module.
- Exact timeouts within section 4's constraints.
- The fast-check fallback for the brief.
- The ADR wording.

## 14. Build rulings (2026-10-20)

Controller rulings made during the build. The sections above have been updated to match; this list is the index.

- **R4.** The Bash corpus and its world are module-level in `tests/test_hook_bash.py`, so the integration tests replay every row through `run_hook`.
- **R7.** `mv`, `rm` and `ln` of an ancestor of a guard file (`.labbrain`, `.claude`, the vault) are denied.
- **R8, R9.** Brief titles pass through `findings.sanitize`; an index failure is appended to the counts line.
- **R10.** Glob and Grep run the link-exposure walk, and deny a link below a search base that points into a root.
- **R11–R13.** Self-protection covers MCP tools; paths embedded in MCP strings are candidates; over-cap strings deny.
- **R14, R16.** MCP writes to vault files and percent-encoded or `file://` spellings are residual risks (section 12).
- **R15.** An unknown `~user` is a relative name, as the shell leaves it.
- **R17.** Candidate extraction also splits path-like tokens on `: [ ] { } @ ! $ % ^ * + ?` and adds the path-like pieces, for MCP strings and Bash (so `file:../x` and `[../x]` are caught). In Bash the extra split applies only to text with no wildcard, so the glob and variable rules still see the whole token.
- **R18.** A Glob `[^…]` class is a negation, as in ripgrep, and is matched as `[!…]`, so `p[^x]i/*` cannot slip past a root `phi`.
- **R19a–R19e.** Substitutions are wildcards, except the whole-word quoted `cat` heredoc in pure `git`/`gh` commands (section 5, rule 2). No `echo` or `printf` form is ever literal.
- **R20, R21, R23.** Glob is a recursive construct with Claude Code's search bases; a pattern with more than 16 literal directories is unsure and denies.
- **R22.** Every path is judged physically and textually.
- **R26.** Rule 8's basename check also runs on quote- and backslash-stripped text.
- **R24.** `<<<` is a herestring, not `<` plus a quoted heredoc (which hid a nested `$(claude)`), and `$"…"` is a quoted string.
- **R27.** An assignment-only command with a redirection still binds (a); special and positional parameters next to path text are wildcards (b).
- **R29.** Special-parameter marks survive binding (for and select lists, assignments, `export`, `declare`, `local`, `readonly`) and are resolved where the value is used: next to path text they are wildcards, alone they are harmless, so `rc=$?; echo $rc` stays allowed.
- **Fix round 5.** Redirections never name programs.
- **Platform.** CLI 2.1.304 has a Glob tool (section 3).
- **Frozen policy.** `POLICIES` lives in `labbrain/frozen.py`.
