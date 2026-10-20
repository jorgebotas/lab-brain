"""PreToolUse write checks: frozen files and the PHI pre-scan (Task 4 fills this in)."""

from __future__ import annotations

from labbrain.hooks.payload import Denial, Payload
from labbrain.hooks.scope import Scope


def check_write(payload: Payload, scope: Scope) -> Denial | None:
    """The denial for this write, or None (stub: nothing found)."""
    return None
