"""The PostToolUse write validator (Task 5 fills this in)."""

from __future__ import annotations

from collections.abc import Mapping

from labbrain.hooks.payload import Payload


def post_tool_use(payload: Payload, env: Mapping[str, str]) -> tuple[int, str]:
    """(exit code, stderr text) for a finished write (stub: nothing to report)."""
    return 0, ""
