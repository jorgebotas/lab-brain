"""The PostToolUse write validator (spec section 7).

After a Write, Edit, MultiEdit or NotebookEdit inside a vault, the written file is validated
against its own vault (never `$LABBRAIN_VAULT`'s): schema, duplicate IDs, and the PHI scan
when protected. Errors exit 2 with the findings on stderr, so Claude fixes them; warnings
only, a clean file, or a file outside any vault stay silent. The findings renderer already
sanitizes messages, and no field value is added here.
"""

from __future__ import annotations

from collections.abc import Mapping

from labbrain.hooks.paths import canonical
from labbrain.hooks.payload import Payload
from labbrain.hooks.scope import vault_of

WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
HEADER = "lab-brain validator: fix these before continuing:\n"


def _target(payload: Payload) -> str:
    for key in ("file_path", "notebook_path"):
        value = payload.tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def post_tool_use(payload: Payload, env: Mapping[str, str]) -> tuple[int, str]:
    """(exit code, stderr text) for a finished write: (2, findings) on errors, else (0, "")."""
    if payload.tool_name not in WRITE_TOOLS:
        return 0, ""
    raw = _target(payload)
    if not raw:
        return 0, ""
    try:
        target = canonical(raw, payload.cwd)
    except (OSError, ValueError, RuntimeError):  # NUL byte, unknown ~user, symlink loop
        return 0, ""  # no such file can have been written
    root = vault_of(target)
    if root is None:
        return 0, ""

    from labbrain.findings import ERROR, render
    from labbrain.validate import validate_path

    errors = [f for f in validate_path(target, vault=root) if f.severity == ERROR]
    if not errors:
        return 0, ""
    return 2, HEADER + render(errors, "text")
