"""Daily activity log: one line per writing-skill action in log/YYYY-MM-DD.md.

No frontmatter, so vault templates can mark log/ with git's union merge driver
and concurrent appends from two lab members never conflict.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from labbrain.layout import LOG_DIR


def append(root: Path, text: str, *, when: datetime, author: str | None = None) -> Path:
    message = " ".join(text.split())
    if not message:
        raise ValueError("log text is empty")
    path = root / LOG_DIR / f"{when:%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"- {when:%H:%M}" + (f" [{author}]" if author else "") + f" {message}\n"
    prefix = ""
    if path.is_file() and path.stat().st_size and not path.read_bytes().endswith(b"\n"):
        prefix = "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + line)
    return path
