"""The Bash command rules of the data guard (Task 3 fills this in)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from labbrain.hooks.payload import Denial
from labbrain.hooks.scope import Scope


def check_command(
    command: str, cwd: Path, scope: Scope, env: Mapping[str, str], session_id: str
) -> Denial | None:
    """The denial for this Bash command, or None (stub: nothing found)."""
    return None
