"""The data guard and guard self-protection for PreToolUse (Task 2 fills this in)."""

from __future__ import annotations

from labbrain.hooks.payload import Denial, Payload
from labbrain.hooks.scope import Scope


def check_tool(payload: Payload, scope: Scope) -> Denial | None:
    """The denial for this tool call under the data guard, or None (stub: nothing found)."""
    return None
