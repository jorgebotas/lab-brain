"""Links into protected roots below a directory: the bounded walk of Bash rule 6b.

A recursive command that follows symlinks reaches a protected root through any link below
its start directory that points into the root (or into one of the root's ancestors). The
walk lists such links without following any link itself, skips version-control and
virtual-environment directories and the protected roots, and stops at the first such link
or after `WALK_LIMIT` entries: a truncated walk means "unknown", and the caller denies. Results are cached per
session and per start directory under `$CLAUDE_PLUGIN_DATA`. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labbrain.hooks.paths import Targets, canonical, fold

WALK_LIMIT: int = 20_000
SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}
)


@dataclass(frozen=True)
class LinkScan:
    found: bool  # a link below the start points into (or above) a protected root
    truncated: bool  # the walk stopped at WALK_LIMIT entries, so the answer is unknown


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _cache_file(cache_dir: Path, session_id: str) -> Path:
    """The session's cache file; the id is hashed, so it can never escape `exposure/`."""
    return cache_dir / "exposure" / f"{_digest(session_id)}.json"


def _targets_key(targets: Targets) -> str:
    """A key for the protected roots, so a cache written for other roots is not reused."""
    return _digest("\0".join(sorted(str(root.path) for root in targets.roots)))


def _load(file: Path, key: str) -> dict[str, LinkScan]:
    """The cached results for roots `key`; anything unreadable or misshapen is ignored."""
    try:
        data: Any = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("targets") != key:
        return {}
    starts = data.get("starts")
    if not isinstance(starts, dict):
        return {}
    results: dict[str, LinkScan] = {}
    for start, value in starts.items():
        if (
            isinstance(start, str)
            and isinstance(value, list)
            and len(value) == 2
            and all(isinstance(flag, bool) for flag in value)
        ):
            results[start] = LinkScan(value[0], value[1])
    return results


def _store(file: Path, key: str, results: dict[str, LinkScan]) -> None:
    """Write the cache atomically; a cache that cannot be written is simply skipped."""
    data = {"targets": key, "starts": {s: [r.found, r.truncated] for s, r in results.items()}}
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        partial = file.with_name(f"{file.name}.{os.getpid()}.tmp")
        partial.write_text(json.dumps(data), encoding="utf-8")
        os.replace(partial, file)
    except OSError:
        return


def _identity(path: str | Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (st.st_dev, st.st_ino)


def _exposes(link: str, targets: Targets) -> bool:
    """Whether following `link` reaches a protected root. A link that cannot be resolved
    (a loop) counts as reaching one."""
    try:
        target = canonical(link)
        return targets.containing(target) is not None or bool(targets.under(target))
    except (OSError, RuntimeError, ValueError):
        return True


def _walk(begin: Path, targets: Targets) -> LinkScan:
    root_keys = [fold(root.path) for root in targets.roots]
    root_ids = {i for i in (_identity(root.path) for root in targets.roots) if i is not None}
    seen = 0
    pending = [str(begin)]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as listing:
                entries = list(listing)
        except OSError:
            continue  # unreadable here, so unreadable for the command too
        for entry in entries:
            seen += 1
            if seen > WALK_LIMIT:
                return LinkScan(False, True)
            try:
                if entry.is_symlink():
                    if _exposes(entry.path, targets):
                        return LinkScan(True, False)  # one is enough (final review item 10)
                elif entry.is_dir(follow_symlinks=False) and entry.name not in SKIP_DIRS:
                    st = entry.stat(follow_symlinks=False)
                    if fold(entry.path) in root_keys or (st.st_dev, st.st_ino) in root_ids:
                        continue  # a protected root itself: rule 6a's business
                    pending.append(entry.path)
            except OSError:
                continue
    return LinkScan(False, False)


def links_under(start: Path, targets: Targets, cache_dir: Path | None, session_id: str) -> LinkScan:
    """Whether a symlink below `start` leads into a protected root, by a bounded walk.

    The walk follows no link and skips SKIP_DIRS and the protected roots. With a
    `cache_dir` (`$CLAUDE_PLUGIN_DATA`), results are cached per session and per canonical
    start in `<cache_dir>/exposure/<sha256(session_id)[:16]>.json`.
    """
    begin = canonical(start)
    if cache_dir is None:
        return _walk(begin, targets)
    file = _cache_file(cache_dir, session_id)
    key = _targets_key(targets)
    cached = _load(file, key)
    hit = cached.get(str(begin))
    if hit is not None:
        return hit
    scan = _walk(begin, targets)
    cached[str(begin)] = scan
    _store(file, key, cached)
    return scan
