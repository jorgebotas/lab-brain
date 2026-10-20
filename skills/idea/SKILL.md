---
name: idea
description: Capture an idea as a note in a lab-brain vault's ideas inbox. Use only when the user explicitly asks to capture, save or jot down an idea, for example with /lab-brain:idea.
argument-hint: <idea text>
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Capture an idea

The idea:

$ARGUMENTS

Capture it without asking any questions, in one Bash call.

1. Title: the idea's first sentence, cut to at most 80 characters, without a trailing period and without any leading `#` characters or spaces.
2. Summary: the first sentence, without any leading `#` characters or spaces.
3. Body: the full idea text as given, except that every line starting with `## ` starts with `### ` instead. Do not otherwise rewrite it.
4. Tags: zero to three lowercase words that already appear in the idea. Do not invent topics.
5. Run this, with every value in single quotes attached to its option by `=` (write a `'` inside a value as `'\''`). Repeat `--tag=` once per tag, or leave it out:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new idea --title='<title>' --author claude --summary='<summary>' --body='<body>' --tag='<tag>' --finish='idea: <title>'
   ```

6. The command prints the note's path, then the check results. Exit 0 means done: tell the user the note's ID in one line.
7. Exit 1 means the note failed validation. Read the findings, fix the note with the Edit tool, then run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log='idea: <title>' --author claude`.
8. Exit 2 with `matches a protected-data pattern` means the engine wrote nothing because the text looks like protected data. Do not run it again with the same text. Tell the user which part (title, summary or body) to rephrase and the rule the message names, without quoting the matched text, and stop.
9. Any other exit 2 means the engine refused. Show its message and stop.

## Do not

- Do not ask questions, rewrite the idea beyond step 3, or add your own commentary to the note.
- Do not invent IDs, hypotheses, protocols, datasets or metric values, or tags that are not in the text.
- Do not edit `index.md`, the log, anything under `raw/`, or a frozen note.
- Do not paste text that `phi-scan` or the engine matched.
- In a vault with `protected_data` on, never put identifiers or individual-level details in the title, summary or body; if the idea holds any, tell the user so and stop.
- Do not write outside the vault.
- Do not use shell variables or command substitution.
