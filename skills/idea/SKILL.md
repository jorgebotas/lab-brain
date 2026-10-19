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

1. Title: the idea's first sentence, cut to at most 80 characters, without a trailing period.
2. Tags: zero to three lowercase words that already appear in the idea. Do not invent topics.
3. Run this, with every value in single quotes (write a `'` inside a value as `'\''`). Repeat `--tag` once per tag, or leave it out:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new idea --title '<title>' --author claude --summary '<first sentence>' --body '<the full idea text>' --tag '<tag>' --finish 'idea: <title>'
   ```

4. The command prints the note's path, then the check results. Exit 0 means done: tell the user the note's ID in one line.
5. Exit 1 means the note failed validation. Read the findings, fix the note with the Edit tool, then run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log 'idea: <title>' --author claude`.
6. Exit 2 means the engine refused. Show its message and stop.

## Do not

- Do not ask questions, rewrite the idea, or add your own commentary to the note.
- Do not invent IDs, or tags that are not in the text.
- Do not use shell variables or command substitution.
- Do not edit `index.md` or the log by hand.
