"""The SessionStart brief (Task 5 fills this in)."""

from __future__ import annotations

from collections.abc import Mapping

from labbrain.hooks.payload import Payload


def session_start(payload: Payload, env: Mapping[str, str]) -> tuple[int, str, str]:
    """(exit code, stdout, stderr) for a session start (stub: no brief)."""
    return 0, "", ""
