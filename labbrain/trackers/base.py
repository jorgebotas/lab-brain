"""The tracker adapter protocol (parent spec section 9).

`search` joins the protocol in M7, with its first real user.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, Protocol, TypedDict

from labbrain.errors import EngineError

RunStatus = Literal["running", "finished", "failed", "unknown"]
RUN_STATUSES: tuple[str, ...] = ("running", "finished", "failed", "unknown")
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class RunRecord(TypedDict):
    run_id: str
    name: str | None
    url: str | None
    status: RunStatus
    started_at: datetime | None
    ended_at: datetime | None
    config: dict[str, Any]  # flattened with dot keys
    summary: dict[str, float]
    tags: list[str]
    git_sha: str | None
    git_dirty: bool | None
    notes: str | None


class TrackerError(EngineError):
    """A tracker cannot serve the request."""


class TrackerAdapter(Protocol):
    name: str

    def fetch(self, run_ids: Sequence[str]) -> list[RunRecord]: ...

    def run_url(self, run_id: str) -> str | None: ...
