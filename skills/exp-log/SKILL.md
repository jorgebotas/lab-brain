---
name: exp-log
description: Log tracker runs as an experiment note in a lab-brain vault. Use only when the user explicitly asks to log runs or an experiment, for example with /lab-brain:exp-log.
argument-hint: <run-id...> [--parent EXP-ID] [--into EXP-ID] [--planned]
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Log an experiment

Arguments: $ARGUMENTS

Run IDs are the arguments that are not flags. `--parent EXP-ID` names the experiment these runs change. `--into EXP-ID` names a planned experiment to fill in. `--planned` means the runs do not exist yet.

Pass free text (titles, summaries, hypotheses, names) inside single quotes, attached to its option by `=` as in `--title='<short title>'` (write a `'` as `'\''`). Pass IDs unquoted, exactly as the engine prints them; quote a run ID the user gave only if it holds anything but letters, digits, `.`, `_` and `-`. Never use shell variables or command substitution.

## Runs that exist

1. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain tracker fetch <run-id...>`. It prints one JSON object per run, with `config`, `summary`, `status`, `tags`, `notes`, `protocol`, `dataset` and `headline`. If it exits non-zero, show the message and stop.
2. Hypothesis: with `--into`, leave out `--hypothesis` unless the user gives a new one; the planned note already holds it, and the flag replaces only its frontmatter `hypothesis:` (see step 6). Otherwise use one only if the runs' `notes` or `tags` state it, or ask the user. Never invent one.
3. Protocol: with `--into`, do not ask; leave out `--protocol` and the engine uses the planned note's protocol, then the runs'. Otherwise use the runs' `protocol`. If it is null, ask the user, offering the IDs from `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain list --type protocol`. Never invent one.
4. Dataset: with `--into`, do not ask; leave out `--dataset` and the engine uses the planned note's dataset, then the runs'. Otherwise use the runs' `dataset`. If it is null, ask the user, offering the IDs from `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain list --type dataset`. If none fits, say so and suggest the user create one with `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new dataset --title='<title>' --author='<their lab_members handle>' --finish='dataset: <title>'`, which also validates and indexes it. Do not log until it exists.
5. Record the experiment in one call. Leave out `--parent`, `--protocol` or `--dataset` when you have no value for them. If the user passed `--into` or names a planned experiment for these runs, pass `--into <EXP-ID>` instead of `--title`, leave out `--summary` (it is ignored with `--into`), and leave out `--hypothesis` unless the user gave a new one:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain exp record <run-id...> --author claude --title='<short title>' --summary='<one line: what this experiment is>' --hypothesis='<hypothesis>' --parent <EXP-ID> --protocol <EVAL-ID> --dataset <DS-ID> --finish='exp-log: <short title>'
   ```

6. The engine writes the setup diff, the results table and the stamped metrics itself; never retype them.
   - Exit 2 with "required to record finished runs" means a protocol or dataset is missing. Ask the user for it and run step 5 again.
   - Exit 2 with `matches a protected-data pattern`: the engine wrote nothing. Do not run it again with the same text; tell the user whether the title, summary or hypothesis needs rephrasing and the rule the message names, without quoting the matched text, and stop.
   - Any other exit 2: show the message and stop.
   - Exit 1: fix the reported fields with the Edit tool, then run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log='exp-log: <short title>' --author claude`.
   - With `--into`, the engine replaces the Setup and Results blocks it wrote before (marked `<!-- labbrain:setup -->` and `<!-- labbrain:results -->`; never remove those comments). If the runs were still running, run step 5 again with the same `--into <EXP-ID>` once they finish; it replaces the earlier blocks rather than adding a second copy.
   - With `--into` and a new `--hypothesis`: rewrite `## Hypothesis` to match with the Edit tool, then run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log='exp-log: hypothesis' --author claude`.
7. Only if the user asked for an interpretation: add it under `## Interpretation` with the Edit tool, starting with `(agent interpretation, unreviewed)`. Then run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log='exp-log: interpretation' --author claude`.
8. Report the note's ID, its status and the headline metrics in a few lines.

## Planned experiments (`--planned`)

1. Ask the user for the hypothesis if they have not given it.
2. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new experiment --title='<short title>' --author claude --summary='<one line>'`. It prints the note's path. On exit 2, handle it as in step 6 above.
3. With the Edit tool, set `hypothesis:` in the frontmatter, write the hypothesis under `## Hypothesis`, and describe the planned setup under `## Setup`.
4. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log='exp-log: planned <short title>' --author claude`.
5. Tell the user to run `/lab-brain:exp-log <run-id...> --into <EXP-ID>` once the runs exist.

## Do not

- Do not invent IDs, hypotheses, protocols, datasets or metric values.
- Do not copy metrics by hand, or edit the `metrics`, `tracker`, `code` or `config_hash` fields.
- Do not log each run of a group as its own note; one note covers the runs you were given.
- Do not change an experiment that was already `done` before this session; a correction is a new experiment with `supersedes`. The note `exp record` just wrote is yours to fix (steps 6 and 7) until it is committed.
- Do not edit `index.md`, anything under `raw/`, or a frozen note.
- Do not paste text that `phi-scan` or the engine matched.
- In a vault with `protected_data` on, do not put identifiers or individual-level details in the title, summary, hypothesis or sections.
- Do not write outside the vault.
- Do not use shell variables or command substitution.
