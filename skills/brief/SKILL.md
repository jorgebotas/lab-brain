---
name: brief
description: Show where a lab-brain vault's project stands - recent handoffs, running and planned experiments, stale claims, open ideas and lint errors. Use when the user asks where things stand, for a status or a briefing, or at the start of a session in a vault.
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Brief

1. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain brief`.
2. Show its output to the user verbatim, in a code block.
3. If it exits non-zero, show the message and stop.

## Do not

- Do not write or change any note.
- Do not leave out the lint error count.
