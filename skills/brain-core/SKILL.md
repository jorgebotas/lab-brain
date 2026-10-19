---
name: brain-core
description: Conventions for working in a lab-brain research vault. Use in any session whose working directory is inside a lab-brain vault (a folder with .labbrain/config.yaml at or above it), or whenever the user talks about the vault's experiments, ideas, decisions, protocols, claims or handoffs.
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Working in a lab-brain vault

The engine command is `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain`. Type it in full every time. Never store it in a shell variable or use command substitution. Pass any text that comes from the user inside single quotes, writing a `'` inside it as `'\''`, and attach it to its option with `=` (`--title='<title>'`) so a value starting with `-` is not read as a flag.

## Orient first

1. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain vault root`. If it fails, this is not a vault; ignore the rest of this skill.
2. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain config` and note `protected_data`, `data_paths`, `min_cell_size` and `search`.
3. Read `index.md` at the vault root before searching, then search with ripgrep. Use the qmd MCP server only when `search` is `qmd`.

## Write rules

| Folder | Rule |
| --- | --- |
| `raw/` | Never modify or delete. |
| `experiments/` | Append-only; once done before this session, only `status` and `superseded_by` change. The note `exp record` just wrote stays editable until it is committed. |
| `protocols/` | A new version is a new file; a version an experiment uses is frozen. |
| `claims/` | Editable; every edit appends a line to `## History`. |
| `ideas/inbox/` | Create-only; consolidated ideas move to `ideas/archive/` with `git mv`. |
| `concepts/` | Rewritable; must cite their sources. |
| `decisions/` | Append-only; a reversal is a new decision with `supersedes`. |
| `literature/`, `datasets/` | One note per paper or extraction; datasets hold metadata, never data. |
| `manuscripts/` | Human-owned; write only under `manuscripts/_proposals/`. |
| `handoffs/` | Create-only, one per session. |
| `index.md`, `log/` | Written by the engine; never edit them by hand. |

Never delete a note. A correction is a new note with `supersedes: <ID>`.

## IDs, notes and numbers

- IDs come only from the engine (`new`, `new-id`, `exp record`) or from existing notes. Never make one up.
- Never write outside the vault.
- Create notes with `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new <type> --title='<title>' --author claude --summary='<one line>'`. It prints the note's absolute path.
- After editing a note, run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <absolute path> --log='<what you did>' --author claude`. On exit 1, fix the reported fields and run it again.
- Every number copied into a note carries its source: a run ID, an `[[EXP-...]]` link, or `as of YYYY-MM-DD`.
- When the engine exits with an error, show its message to the user and stop. Never write the note by hand instead.

## Protected data (when `protected_data` is true)

- Never read, open, sample or print files under `data_paths`, even if asked. Ask the user to run the command and paste aggregate output.
- The vault holds aggregates only. Counts below `min_cell_size` are written as `<min_cell_size`.
- Never paste text that `phi-scan` matched into a note or a message.
- Never put identifiers or individual-level details in a title, summary, body or hypothesis.
- If `new` or `exp record` exits 2 with `matches a protected-data pattern`, it wrote nothing. Do not retry with the same text: tell the user which field to rephrase, never quoting the matched text, and stop.
- Example records in notes are synthetic and labelled as synthetic.

## Skills

- `/lab-brain:idea <text>`: capture an idea.
- `/lab-brain:exp-log <run-id...> [--parent EXP-ID] [--into EXP-ID] [--planned]`: log runs as an experiment.
- `/lab-brain:decide <summary>`: record a decision.
- `/lab-brain:handoff`: write the session handoff.
- `/lab-brain:brief`: show where the project stands.
