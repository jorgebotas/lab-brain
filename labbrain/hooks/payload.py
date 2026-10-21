"""Hook payloads from stdin, and the denials hooks report. Standard library only."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from labbrain.hooks.paths import ProtectedRoot

MAX_STDIN: int = 4 * 1024 * 1024

# C0 and C1 controls, DEL, and bidirectional formatting characters (as in findings).
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f؜‎‏‪-‮⁦-⁩]+")

_DATA_DENIAL = (
    "lab-brain data guard: {subject} refers to protected data path #{n} ('{configured}'). "
    "Individual-level data must not enter the session. If you need this run, ask the user "
    "to run it themselves and share only aggregate results."
)


class PayloadError(Exception):
    """The hook payload is missing, oversized, not JSON, or not shaped like a payload."""


@dataclass(frozen=True)
class Payload:
    event: str  # hook_event_name
    tool_name: str  # "" for SessionStart
    tool_input: dict[str, Any]  # {} when absent
    cwd: Path  # absolute, from the payload
    session_id: str
    source: str  # SessionStart source, "" otherwise


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise PayloadError(f"{key} is not a string")
    return value


def parse_payload(data: bytes) -> Payload:
    """The payload in `data`. Raises PayloadError; the message never quotes the payload."""
    if len(data) > MAX_STDIN:
        raise PayloadError("payload too large")
    try:
        raw: Any = json.loads(data)
    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeDecodeError are ValueError
        raise PayloadError("payload is not JSON") from None
    if not isinstance(raw, dict):
        raise PayloadError("payload is not an object")
    cwd = raw.get("cwd")
    if not isinstance(cwd, str) or not cwd or "\0" in cwd or not Path(cwd).is_absolute():
        raise PayloadError("payload cwd is missing or not an absolute path")
    tool_input = raw.get("tool_input", {})
    if not isinstance(tool_input, dict):
        raise PayloadError("tool_input is not an object")
    return Payload(
        event=_text(raw, "hook_event_name"),
        tool_name=_text(raw, "tool_name"),
        tool_input=tool_input,
        cwd=Path(cwd),
        session_id=_text(raw, "session_id"),
        source=_text(raw, "source"),
    )


@dataclass(frozen=True)
class Denial:
    rule: str  # one of: "data-guard", "guard-config", "frozen-file", "phi", "config"
    message: str  # already sanitized, single paragraph


_UNCHECKED = (
    "lab-brain data guard: {subject} cannot be checked safely here (too many files to check "
    "for links, input too large, or a form the guard cannot read). Narrow the search folder "
    "or ask the user to run it."
)


def unchecked_denial(subject: str) -> Denial:
    """Final review item 2: the data-guard denial for `subject` when the guard hit one of its
    bounds (a link walk past its entry limit, too much input) or a form it cannot judge, and
    no particular protected root is implicated."""
    return Denial("data-guard", _UNCHECKED.format(subject=subject))


def data_denial(root: ProtectedRoot, subject: str) -> Denial:
    """The data-guard denial for `subject` (e.g. "this Bash command") touching `root`."""
    configured = " ".join(_CONTROL.sub(" ", root.configured).split())
    message = _DATA_DENIAL.format(subject=subject, n=root.index, configured=configured)
    return Denial("data-guard", message)
