"""Tracker adapters: choose one from the vault config, and describe runs for skills."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from labbrain.confighash import config_hash
from labbrain.trackers.base import RunRecord, TrackerAdapter, TrackerError
from labbrain.vault import Config

LATER_BACKENDS = frozenset({"wandb", "mlflow"})


def get_adapter(config: Config, root: Path) -> TrackerAdapter:
    backend = config.tracker.backend
    if backend == "local":
        from labbrain.trackers.local import LocalAdapter

        return LocalAdapter.from_config(config, root)
    if backend in LATER_BACKENDS:
        raise TrackerError(f"tracker backend '{backend}' arrives in a later engine version")
    if backend == "none":
        raise TrackerError("tracker backend 'none' is not supported by exp record yet")
    raise TrackerError("unknown tracker backend")


def headline(summary: Mapping[str, float], patterns: Iterable[str]) -> dict[str, float]:
    """The summary metrics matching any pattern (case-sensitive), or all when none are set."""
    patterns = list(patterns)
    if not patterns:
        return dict(summary)
    return {k: v for k, v in summary.items() if any(fnmatch.fnmatchcase(k, p) for p in patterns)}


def _config_str(config: Mapping[str, Any], key: str) -> str | None:
    value = config.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def describe(record: RunRecord, config: Config) -> dict[str, Any]:
    """`record` as JSON-ready data, plus config_hash, protocol, dataset and headline."""
    out: dict[str, Any] = dict(record)
    for key in ("started_at", "ended_at"):
        value = record[key]
        out[key] = value.isoformat() if value is not None else None
    out["config_hash"] = config_hash(record["config"], config.hash_ignore)
    out["protocol"] = _config_str(record["config"], config.protocol_key)
    out["dataset"] = _config_str(record["config"], config.dataset_key)
    out["headline"] = headline(record["summary"], config.headline_metrics)
    return out
