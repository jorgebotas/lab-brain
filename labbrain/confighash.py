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

from labbrain.notes import safe_load, well_formed


def flatten(config: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """`config` with nested mappings joined into dot keys (`{"a": {"b": 1}}` → `a.b`).

    Raises ValueError when two keys flatten to the same name (`a.b` beside `a: {b: …}`),
    so no value is dropped silently. The message names no key.
    """
    flat: dict[str, Any] = {}
    for key, value in config.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            parts = flatten(value, f"{name}.")
        else:
            parts = {name: value}
        for part, item in parts.items():
            if part in flat:
                raise ValueError("keys collide when flattened")
            flat[part] = item
    return flat


def is_ignored(key: str, patterns: Iterable[str]) -> bool:
    """True when a flattened config key matches a hash_ignore pattern (case-sensitive)."""
    return any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)


def _json_key(key: Any) -> str:
    """`key` as the string json.dumps would write for it (`true`, `null`, `3`, `1.5`),
    or str() of a key JSON cannot encode (a YAML date, say)."""
    if isinstance(key, str):
        return key
    if key is None or isinstance(key, bool | int | float):
        return json.dumps(key)
    return str(key)


def string_keys(value: Any) -> Any:
    """`value` with every mapping key a string, recursively (lists and tuples become
    lists), so JSON can encode and sort it: YAML allows date or mixed-type keys. Keys
    JSON can encode are written as json.dumps writes them, so ordinary output is
    unchanged."""
    if isinstance(value, Mapping):
        return {_json_key(key): string_keys(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [string_keys(item) for item in value]
    return value


def config_hash(config: Mapping[str, Any], ignore: Iterable[str]) -> str:
    """`sha256:` + the SHA-256 of the kept flattened keys as sorted, compact JSON.

    Mappings nested inside lists keep their own keys, which YAML allows to be of mixed
    types (`[{1: a, b: c}]`) that JSON cannot sort. Only for such a config, every mapping
    key is stringified (recursively) before hashing; every other config hashes exactly
    as before, so recorded hashes stay comparable.
    """
    patterns = list(ignore)
    kept = {key: value for key, value in flatten(config).items() if not is_ignored(key, patterns)}
    try:
        payload = json.dumps(kept, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        payload = json.dumps(string_keys(kept), sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_run_config(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix == ".json" else safe_load(text)
    except (OSError, ValueError, TypeError, RecursionError, yaml.YAMLError):
        # ValueError covers UnicodeDecodeError, JSONDecodeError and impossible YAML dates.
        raise ValueError(f"cannot read run config {path.name}") from None
    if not isinstance(data, dict):
        raise ValueError(f"run config {path.name} must be a mapping")
    if not well_formed(data):
        raise ValueError(f"cannot read run config {path.name}")
    return data
