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


# Deeper run data is refused: it is not a real config, and the recursive helpers that
# handle run data (flatten, json.dumps) would hit Python's recursion limit.
MAX_DEPTH = 200


def well_formed(data: Any) -> bool:
    """True when loaded run data nests at most MAX_DEPTH levels (so has no cycle, as a
    recursive YAML alias makes) and every string in it, key or value, encodes as UTF-8
    (JSON and YAML escapes can produce lone surrogates, which cannot be written)."""
    stack: list[tuple[Any, int]] = [(data, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return False
        elif isinstance(value, Mapping | list | tuple):
            if depth > MAX_DEPTH:
                return False
            items = [*value.keys(), *value.values()] if isinstance(value, Mapping) else value
            stack.extend((item, depth + 1) for item in items)
    return True


def is_ignored(key: str, patterns: Iterable[str]) -> bool:
    """True when a flattened config key matches a hash_ignore pattern (case-sensitive)."""
    return any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)


def _string_keys(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _string_keys(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_string_keys(item) for item in value]
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
        payload = json.dumps(_string_keys(kept), sort_keys=True, separators=(",", ":"), default=str)
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
