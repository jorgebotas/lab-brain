"""config_hash: SHA-256 over the flattened run config, minus hash_ignore keys.

Implemented now (before /exp-log exists) so every caller hashes identically
and duplicate-config compares like with like.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from labbrain.notes import safe_load


def flatten(config: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in config.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            flat.update(flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def is_ignored(key: str, patterns: Iterable[str]) -> bool:
    """True when a flattened config key matches a hash_ignore pattern (case-sensitive)."""
    return any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)


def config_hash(config: Mapping[str, Any], ignore: Iterable[str]) -> str:
    patterns = list(ignore)
    kept = {key: value for key, value in flatten(config).items() if not is_ignored(key, patterns)}
    payload = json.dumps(kept, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_run_config(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix == ".json" else safe_load(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read run config {path.name}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"run config {path.name} must be a mapping")
    return data
