"""frozen-edit: append-only notes may not be rewritten (diff against --base).

Only files git reports as changed are examined. Base versions are matched by
ID (filename), so a note moved between folders is compared, not reported as
deleted. Field values never appear in messages: a status is named only when it
is one of its type's schema enum values, and a field only when it is a schema
field name.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, get_args

from labbrain import gitutil
from labbrain.findings import ERROR, INFO, Finding
from labbrain.layout import RAW_DIR, is_note_rel
from labbrain.lint import LintContext, rule
from labbrain.notes import Note, parse_note_text
from labbrain.schema import MODELS

RULE = "frozen-edit"


@dataclass(frozen=True)
class Policy:
    frozen_statuses: frozenset[str] | None  # None: frozen as soon as it exists at base
    mutable: frozenset[str]
    transitions: frozenset[tuple[str, str]]


POLICIES: dict[str, Policy] = {
    "experiment": Policy(
        frozenset({"done", "failed", "superseded"}),
        frozenset({"status", "superseded_by", "updated"}),
        frozenset({("done", "superseded"), ("failed", "superseded")}),
    ),
    "protocol": Policy(
        frozenset({"frozen", "retired"}),
        frozenset({"status", "updated"}),
        frozenset({("draft", "frozen"), ("frozen", "retired")}),
    ),
    "decision": Policy(
        frozenset({"accepted", "superseded"}),
        frozenset({"status", "superseded_by", "updated"}),
        frozenset({("accepted", "superseded")}),
    ),
    "dataset": Policy(
        None,
        frozenset({"status", "superseded_by", "updated"}),
        frozenset({("active", "superseded")}),
    ),
    "idea": Policy(
        None,
        frozenset({"status", "consolidated_into", "updated"}),
        frozenset({("open", "consolidated"), ("open", "dropped")}),
    ),
    "handoff": Policy(None, frozenset({"updated"}), frozenset()),
}

# Schema enum values of `status` per note type, and every schema field name.
_STATUS_VALUES: dict[str, frozenset[str]] = {
    name: frozenset(get_args(model.model_fields["status"].annotation))
    for name, model in MODELS.items()
}
_FIELD_NAMES: frozenset[str] = frozenset(
    name for model in MODELS.values() for name in model.model_fields
)


def _status_label(note_type: str, value: str | None) -> str:
    return value if value in _STATUS_VALUES.get(note_type, frozenset()) else "<invalid status>"


def _field_label(key: Any) -> str:
    return f"'{key}'" if isinstance(key, str) and key in _FIELD_NAMES else "<unknown field>"


def _parse_blob(data: bytes, rel: str) -> Note:
    return parse_note_text(data.decode("utf-8", "replace"), Path(rel), rel)


class _DoneProtocolsAtBase:
    """Protocols referenced by a done experiment at base; computed only when needed."""

    def __init__(self, repo: gitutil.Repo, tree: dict[str, str]) -> None:
        self._repo, self._tree = repo, tree
        self._value: set[str] | None = None

    def get(self) -> set[str]:
        if self._value is None:
            rels = [r for r in self._tree if r.startswith("experiments/") and is_note_rel(r)]
            blobs = gitutil.read_blobs(self._repo, [self._tree[r] for r in rels])
            self._value = set()
            for rel in rels:
                note = _parse_blob(blobs[self._tree[rel]], rel)
                protocol = note.get_str("protocol")
                if note.get_str("status") == "done" and protocol:
                    self._value.add(protocol)
        return self._value


def _frozen_at_base(note: Note, policy: Policy, done_protocols: _DoneProtocolsAtBase) -> bool:
    if policy.frozen_statuses is None or note.get_str("status") in policy.frozen_statuses:
        return True
    return note.type == "protocol" and note.stem in done_protocols.get()


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _compare(base: Note, current: Note, policy: Policy) -> Iterator[Finding]:
    if base.data is None:
        return  # nothing reliable to compare against
    if current.data is None:
        yield Finding(current.rel, current.error_line, RULE, ERROR, "frozen note no longer parses")
        return
    for key in sorted(set(base.data) | set(current.data), key=str):
        if key in policy.mutable:
            continue
        if _plain(base.data.get(key)) != _plain(current.data.get(key)):
            message = f"frozen field {_field_label(key)} changed"
            yield Finding(current.rel, 1, RULE, ERROR, message)
    old, new = base.get_str("status"), current.get_str("status")
    if "status" in policy.mutable and old != new and (old, new) not in policy.transitions:
        note_type = base.type or ""
        old_label, new_label = _status_label(note_type, old), _status_label(note_type, new)
        message = f"status change {old_label} → {new_label} is not allowed on a frozen {note_type}"
        yield Finding(current.rel, 1, RULE, ERROR, message)
    matcher = difflib.SequenceMatcher(
        None, base.body.splitlines(), current.body.splitlines(), autojunk=False
    )
    for tag, _i1, _i2, j1, _j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            message = "existing body lines were modified or deleted; only insertions are allowed"
            yield Finding(current.rel, current.body_line + j1, RULE, ERROR, message)


@rule(RULE, ERROR, "Frozen notes changed outside allowed fields, deleted, or raw/ files edited")
def frozen_edit(ctx: LintContext) -> Iterator[Finding]:
    repo = gitutil.open_repo(ctx.vault.root)
    if repo is None:
        yield Finding("", 0, RULE, INFO, "not a git repository; frozen-edit skipped")
        return
    base = gitutil.resolve_ref(repo, ctx.base)
    if base is None:
        message = f"base revision {ctx.base} not found; frozen-edit skipped"
        yield Finding("", 0, RULE, INFO, message)
        return
    changes = gitutil.changed_files(repo, base)
    for status, rel in changes:
        if rel.startswith(f"{RAW_DIR}/"):
            verb = "deleted" if status == "D" else "modified"
            yield Finding(rel, 0, RULE, ERROR, f"raw/ files are immutable; this file was {verb}")
    note_changes = [(s, rel) for s, rel in changes if s in ("M", "D", "T") and is_note_rel(rel)]
    if not note_changes:
        return
    tree = gitutil.ls_tree(repo, base)
    blobs = gitutil.read_blobs(repo, [tree[rel] for _, rel in note_changes if rel in tree])
    done_protocols = _DoneProtocolsAtBase(repo, tree)
    for status, rel in note_changes:
        if rel not in tree:
            continue
        base_note = _parse_blob(blobs[tree[rel]], rel)
        policy = POLICIES.get(base_note.type or "")
        if policy is None or not _frozen_at_base(base_note, policy, done_protocols):
            continue
        current = ctx.vault.get(base_note.stem) if status == "D" else ctx.vault.by_rel.get(rel)
        if current is None:
            message = f"frozen {base_note.type} {base_note.stem} was deleted; supersede it instead"
            yield Finding(rel, 0, RULE, ERROR, message)
            continue
        yield from _compare(base_note, current, policy)
