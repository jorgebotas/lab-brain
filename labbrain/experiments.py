"""Experiment notes from tracker runs: config diffs (`tracker diff`) and `exp record`."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from labbrain.confighash import is_ignored
from labbrain.errors import EngineError
from labbrain.findings import display_id
from labbrain.vault import Vault

_ABSENT = object()


class RecordError(EngineError):
    """`tracker diff` or `exp record` cannot proceed."""


@dataclass(frozen=True)
class ConfigDiff:
    parent: str
    added: dict[str, Any]
    removed: dict[str, Any]
    changed: dict[str, tuple[Any, Any]]
    varied_here: list[str]
    varied_parent: list[str]

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def split_common(
    configs: Sequence[Mapping[str, Any]], ignore: Iterable[str]
) -> tuple[dict[str, Any], list[str]]:
    """(keys equal in every config, keys missing from some or differing), hash_ignore dropped."""
    patterns = list(ignore)
    kept = [{k: v for k, v in c.items() if not is_ignored(k, patterns)} for c in configs]
    common: dict[str, Any] = {}
    varied: list[str] = []
    for key in sorted(set().union(*kept)):
        values = [c[key] for c in kept if key in c]
        if len(values) == len(kept) and all(v == values[0] for v in values[1:]):
            common[key] = values[0]
        else:
            varied.append(key)
    return common, varied


def config_diff(
    parent_id: str,
    parent_configs: Sequence[Mapping[str, Any]],
    child_configs: Sequence[Mapping[str, Any]],
    ignore: Iterable[str],
) -> ConfigDiff:
    patterns = list(ignore)
    parent, varied_parent = split_common(parent_configs, patterns)
    child, varied_here = split_common(child_configs, patterns)
    skip = set(varied_parent) | set(varied_here)
    return ConfigDiff(
        parent=parent_id,
        added={k: child[k] for k in sorted(child) if k not in parent and k not in skip},
        removed={k: parent[k] for k in sorted(parent) if k not in child and k not in skip},
        changed={
            k: (parent[k], child[k])
            for k in sorted(child)
            if k in parent and k not in skip and parent[k] != child[k]
        },
        varied_here=varied_here,
        varied_parent=varied_parent,
    )


def parent_run_ids(vault: Vault, parent_id: str) -> list[str]:
    note = vault.get(parent_id)
    if note is None or note.type != "experiment":
        raise RecordError(f"no experiment with ID {display_id(parent_id, vault.notes)}")
    tracker = note.get("tracker")
    run_ids = tracker.get("run_ids") if isinstance(tracker, dict) else None
    ids = [r for r in run_ids if isinstance(r, str)] if isinstance(run_ids, list) else []
    if not ids:
        raise RecordError(f"parent {parent_id} has no run ids")
    return ids


def escape_cell(text: str) -> str:
    return text.replace("|", "\\|")


def _cell(value: Any) -> str:
    if value is _ABSENT:
        return "—"
    return escape_cell(json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str))


def _varied(keys: Sequence[str], label: str) -> list[str]:
    return [f"{label}: {', '.join(keys)}."] if keys else []


def render_setup(diff: ConfigDiff) -> str:
    link = f"[[{diff.parent}]]"
    if diff.empty:
        lines = [f"Same config as {link} (hash_ignore keys omitted)."]
    else:
        lines = [
            f"Config diff against {link} (hash_ignore keys omitted):",
            "",
            "| key | parent | this |",
            "| --- | --- | --- |",
        ]
        rows: dict[str, tuple[Any, Any]] = {k: (_ABSENT, v) for k, v in diff.added.items()}
        rows.update({k: (v, _ABSENT) for k, v in diff.removed.items()})
        rows.update(diff.changed)
        for key in sorted(rows):
            old, new = rows[key]
            lines.append(f"| {escape_cell(key)} | {_cell(old)} | {_cell(new)} |")
    extra = _varied(diff.varied_here, "Varied across these runs")
    extra += _varied(diff.varied_parent, "Varied across the parent's runs")
    if extra:
        lines += ["", *extra]
    return "\n".join(lines) + "\n"


def render_runs(run_ids: Sequence[str], varied: Sequence[str]) -> str:
    lines = [f"Runs: {', '.join(run_ids)}.", *_varied(varied, "Varied across these runs")]
    return "\n".join(lines) + "\n"
