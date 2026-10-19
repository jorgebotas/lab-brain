"""The `local` tracker: one directory per run under `<runs_dir>/<run_id>/`.

Files: `config.yaml` (required), `metrics.json` and `meta.json` (optional). Every
path is canonicalised and refused when it lies in a protected data path, so a
symlinked run cannot reach individual-level data.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from labbrain.confighash import flatten, well_formed
from labbrain.findings import sanitize
from labbrain.notes import safe_load
from labbrain.trackers.base import RUN_ID_RE, RUN_STATUSES, RunRecord, TrackerError
from labbrain.vault import Config, resolve_config_path

SHA_RE = re.compile(r"[0-9a-f]{7,40}")


def runs_dir_for(config: Config, root: Path) -> Path:
    base = resolve_config_path(root, config.code_repo) if config.code_repo.strip() else root
    return resolve_config_path(base, config.tracker.runs_dir).resolve()


def protected_roots(config: Config, root: Path) -> list[Path]:
    return [resolve_config_path(root, p).resolve() for p in config.data_paths if p.strip()]


def _error(run_id: str, problem: str) -> TrackerError:
    return TrackerError(sanitize(f"run {run_id}: {problem}"))


def _read_yaml(path: Path, run_id: str) -> dict[str, Any]:
    # ValueError: an impossible date (2026-13-45); RecursionError: very deep nesting.
    try:
        data = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, RecursionError, yaml.YAMLError):
        raise _error(run_id, f"{path.name} is not valid YAML") from None
    if not isinstance(data, dict):
        raise _error(run_id, f"{path.name} is not a mapping")
    if not well_formed(data):  # a recursive alias, or a string that is not UTF-8
        raise _error(run_id, f"{path.name} is not valid YAML")
    return data


def _read_json(path: Path, run_id: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, RecursionError):
        raise _error(run_id, f"{path.name} is not valid JSON") from None
    if not isinstance(data, dict) or not well_formed(data):
        raise _error(run_id, f"{path.name} is not valid JSON")
    return data


def _flat(data: dict[str, Any], name: str, run_id: str) -> dict[str, Any]:
    try:
        return flatten(data)
    except ValueError:
        raise _error(run_id, f"{name} has keys that collide when flattened") from None


def _finite(value: Any) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except OverflowError:  # an integer too large for a float
        return None
    return number if math.isfinite(number) else None


def _numbers(flat: dict[str, Any]) -> dict[str, float]:
    return {key: number for key, value in flat.items() if (number := _finite(value)) is not None}


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (st.st_dev, st.st_ino)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _tags(value: Any) -> list[str]:
    return [t for t in value if isinstance(t, str)] if isinstance(value, list) else []


def _sha(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    return lowered if SHA_RE.fullmatch(lowered) else None


class LocalAdapter:
    name = "local"

    def __init__(self, runs_dir: Path, protected: Sequence[Path] = ()) -> None:
        self.runs_dir = runs_dir
        self.protected = list(protected)
        # File identities catch a differently-cased path on a case-insensitive filesystem,
        # where resolve() does not canonicalise letter case.
        self._protected_ids = {i for p in self.protected if (i := _identity(p)) is not None}

    @classmethod
    def from_config(cls, config: Config, root: Path) -> LocalAdapter:
        return cls(runs_dir_for(config, root), protected_roots(config, root))

    def fetch(self, run_ids: Sequence[str]) -> list[RunRecord]:
        return [self._load(run_id) for run_id in run_ids]

    def run_url(self, run_id: str) -> str | None:
        return self._load(run_id)["url"]

    def _guard(self, path: Path) -> Path:
        real = path.resolve()
        inside = any(real == root or root in real.parents for root in self.protected)
        if not inside and self._protected_ids:
            inside = any(_identity(p) in self._protected_ids for p in (real, *real.parents))
        if inside:
            raise TrackerError("run path is inside a protected data path")
        return real

    def _load(self, run_id: str) -> RunRecord:
        if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
            raise TrackerError("invalid run id")
        self._guard(self.runs_dir)
        run_dir = self._guard(self.runs_dir / run_id)
        config_path = self._guard(run_dir / "config.yaml")
        if not config_path.is_file():
            raise _error(run_id, "config.yaml not found")
        config = _flat(_read_yaml(config_path, run_id), "config.yaml", run_id)
        metrics_path = self._guard(run_dir / "metrics.json")
        has_metrics = metrics_path.is_file()
        metrics = _read_json(metrics_path, run_id) if has_metrics else {}
        summary = _numbers(_flat(metrics, "metrics.json", run_id))
        meta_path = self._guard(run_dir / "meta.json")
        meta = _read_json(meta_path, run_id) if meta_path.is_file() else {}
        status = meta.get("status")
        if not isinstance(status, str) or status not in RUN_STATUSES:
            status = "finished" if has_metrics else "unknown"
        dirty = meta.get("git_dirty")
        return RunRecord(
            run_id=run_id,
            name=_text(meta.get("name")),
            url=_text(meta.get("url")),
            status=status,  # type: ignore[typeddict-item]
            started_at=_when(meta.get("started_at")),
            ended_at=_when(meta.get("ended_at")),
            config=config,
            summary=summary,
            tags=_tags(meta.get("tags")),
            git_sha=_sha(meta.get("git_sha")),
            git_dirty=dirty if isinstance(dirty, bool) else None,
            notes=_text(meta.get("notes")),
        )
