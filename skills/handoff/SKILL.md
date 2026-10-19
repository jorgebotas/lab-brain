---
name: handoff
description: Write a session handoff note in a lab-brain vault. Use when the user asks for a handoff, when a working session in a vault is ending, when work passes to another agent, or when you are a subagent finishing delegated work in a vault.
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Write a handoff

Pass every value inside single quotes (write a `'` as `'\''`). Never use shell variables or command substitution.

1. Collect what changed:
   - In the vault: `git status --short` and `git diff --stat`.
   - Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain config --key code_repo`. If it prints a path, resolve it against the vault root from `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain vault root`. If that path exists, also run `git -C <path> status --short` and `git -C <path> diff --stat`.
2. Create the note. Use your own agent name for `--agent` if you were dispatched as a named subagent, otherwise `claude`. It prints the note's path:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new handoff --title '<what this session did, in a few words>' --author claude --agent claude --summary '<one line: what the next agent should know first>'
   ```

3. With the Edit tool:
   - set `session_goal:` to the session's goal in one line;
   - set `files_touched:` to the changed paths from step 1;
   - fill in `## Done`, `## In progress`, `## Blockers` and `## Next step for whoever picks this up`, linking notes as `[[ID]]`.
4. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log 'handoff: <title>' --author claude`. On exit 1, fix the reported fields and run it again.
5. Tell the user the handoff's ID.

## Do not

- Do not edit an earlier handoff; write a new one.
- Do not list files that step 1 did not show.
- Do not paste secrets, data rows or text that `phi-scan` matched.
- Do not use shell variables or command substitution.
