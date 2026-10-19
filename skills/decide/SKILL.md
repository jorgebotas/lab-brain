---
name: decide
description: Record a decision (an ADR) in a lab-brain vault's decisions folder. Use only when the user explicitly asks to record a decision or write an ADR, for example with /lab-brain:decide.
argument-hint: <decision summary>
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Record a decision

The decision: $ARGUMENTS

Pass every value inside single quotes (write a `'` as `'\''`). Never use shell variables or command substitution.

1. From the conversation, draft four sections: Context (why a decision was needed), Decision (what was decided), Alternatives considered, and Consequences.
2. If the conversation mentions no alternatives, ask the user which were considered. Do not invent them.
3. If this decision reverses or replaces an earlier one, find it with `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain list --type decision` and confirm its ID with the user.
4. Create the note. Use `--status proposed` instead of `accepted` when the user calls it a proposal. It prints the note's path:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new decision --title '<short title>' --author claude --summary '<one line: what was decided>' --status accepted
   ```

5. With the Edit tool, fill in `## Context`, `## Decision`, `## Alternatives considered` and `## Consequences`. If it replaces an earlier decision, set `supersedes: <ADR-ID>` in the frontmatter.
6. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log 'decide: <short title>' --author claude`. It also marks the superseded decision; never edit the old decision yourself. On exit 1, fix the reported fields and run it again.
7. Tell the user the decision's ID in one line.

## Do not

- Do not edit or delete an existing decision; a reversal is a new decision with `supersedes`.
- Do not invent alternatives or consequences that the conversation does not support.
- Do not invent IDs, hypotheses, protocols, datasets or metric values.
- Do not edit `index.md`, anything under `raw/`, or a frozen note.
- Do not paste text that `phi-scan` matched.
- Do not write outside the vault.
- Do not use shell variables or command substitution.
