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

Pass every value inside single quotes, attached to its option by `=` as in `--title='<short title>'` (write a `'` as `'\''`). Never use shell variables or command substitution.

1. From the conversation, draft four sections: Context (why a decision was needed), Decision (what was decided), Alternatives considered, and Consequences.
2. If the conversation mentions no alternatives, ask the user which were considered. Do not invent them.
3. If this decision reverses or replaces an earlier one, find it with `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain list --type decision` and confirm its ID with the user.
4. Create the note. Use `--status proposed` instead of `accepted` when the user calls it a proposal. It prints the note's path:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new decision --title='<short title>' --author claude --summary='<one line: what was decided>' --status accepted
   ```

5. Exit 2 with `matches a protected-data pattern` means the engine wrote nothing. Do not run it again with the same text: tell the user whether the title or the summary needs rephrasing and the rule the message names, without quoting the matched text, and stop. Show any other exit 2 message and stop.
6. With the Edit tool, fill in `## Context`, `## Decision`, `## Alternatives considered` and `## Consequences`. If it replaces an earlier decision, set `supersedes: <ADR-ID>` in the frontmatter.
7. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log='decide: <short title>' --author claude`. On exit 1, fix the reported fields and run it again.
8. For an `accepted` decision, finish also marks the superseded decision. For a `proposed` one, `supersedes:` takes effect only once it is accepted: the old decision stays as it is. When the user accepts this one, set `status: accepted` with the Edit tool and run step 7 again; finish marks the old decision then. Either way, never edit the old decision yourself.
9. Tell the user the decision's ID in one line.

## Do not

- Do not edit or delete an existing decision; a reversal is a new decision with `supersedes`.
- Do not invent alternatives or consequences that the conversation does not support.
- Do not invent IDs, hypotheses, protocols, datasets or metric values.
- Do not edit `index.md`, anything under `raw/`, or a frozen note.
- Do not paste text that `phi-scan` or the engine matched.
- In a vault with `protected_data` on, do not put identifiers or individual-level details in the title, summary or sections.
- Do not write outside the vault.
- Do not use shell variables or command substitution.
