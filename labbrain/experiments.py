"""Experiment notes from tracker runs: config diffs (`tracker diff`) and `exp record`."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, get_args

from ruamel.yaml.comments import CommentedMap

from labbrain.confighash import is_ignored
from labbrain.errors import EngineError
from labbrain.findings import display_id, strip_controls
from labbrain.notes import (
    H2_RE,
    HEADING_RE,
    Note,
    atomic_write,
    split_frontmatter,
    update_frontmatter_text,
)
from labbrain.scaffold import FENCES, create, one_line
from labbrain.schema import ExperimentNote
from labbrain.trackers.base import RunRecord, TrackerAdapter
from labbrain.vault import Config, Vault, resolve_config_path

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
        raise RecordError(f"parent {display_id(parent_id, vault.notes)} has no run ids")
    return ids


def escape_cell(text: str) -> str:
    """`text` safe in a table cell: on one line (no injected rows or headings), `|` escaped."""
    return one_line(text).replace("|", "\\|")


def _cell(value: Any) -> str:
    if value is _ABSENT:
        return "—"
    return escape_cell(json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str))


def _varied(keys: Sequence[str], label: str) -> list[str]:
    return [f"{label}: {', '.join(one_line(k) for k in keys)}."] if keys else []


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
    runs = ", ".join(one_line(r) for r in run_ids)
    lines = [f"Runs: {runs}.", *_varied(varied, "Varied across these runs")]
    return "\n".join(lines) + "\n"


SPLITS = frozenset({"train", "val", "valid", "validation", "test"})
FILLABLE = ("planned", "running")
_EXPERIMENT_STATUSES = frozenset(get_args(ExperimentNote.model_fields["status"].annotation))


@dataclass
class RecordRequest:
    run_ids: list[str]
    author: str
    now: datetime
    title: str | None = None
    into: str | None = None
    parent: str | None = None
    protocol: str | None = None
    dataset: str | None = None
    hypothesis: str | None = None
    summary: str = ""
    links: list[str] = field(default_factory=list)


def split_of(name: str) -> str | None:
    head = re.split(r"[/.]", name, maxsplit=1)[0]
    return head if head in SPLITS and head != name else None


def run_status(statuses: Iterable[str]) -> str:
    statuses = list(statuses)
    if "failed" in statuses:
        return "failed"
    if any(s in ("running", "unknown") for s in statuses):
        return "running"
    return "done"


def _flow(data: Mapping[str, Any]) -> CommentedMap:
    mapping = CommentedMap(data)
    mapping.fa.set_flow_style()
    return mapping


def _status_label(value: str | None) -> str:
    return value if value in _EXPERIMENT_STATUSES else "<invalid status>"


def _shared(values: Iterable[str | None], what: str) -> str | None:
    found = {v for v in values if v}
    if len(found) > 1:
        raise RecordError(f"runs disagree on {what}; pass --{what}")
    return found.pop() if found else None


def _resolve(
    given: str | None, planned: str | None, runs: Iterable[str | None], what: str
) -> str | None:
    if given:
        return given
    if planned:
        return planned
    return _shared(runs, what)


def _require(vault: Vault, note_id: str | None, note_type: str) -> None:
    if note_id is None:
        return
    note = vault.get(note_id)
    if note is None or note.type != note_type:
        raise RecordError(f"{note_type} not found")


def _fillable(vault: Vault, note_id: str) -> Note:
    note = vault.get(note_id)
    if note is None or note.type != "experiment":
        raise RecordError(f"no experiment with ID {display_id(note_id, vault.notes)}")
    status = note.get_str("status")
    if status not in FILLABLE:
        raise RecordError(
            f"{display_id(note_id, vault.notes)} is {_status_label(status)};"
            " only planned or running experiments can be filled in"
        )
    return note


def resolve_code(records: Sequence[RunRecord], config: Config, root: Path) -> CommentedMap | None:
    from labbrain.codeinfo import CodeError, code_sha

    repo = config.code_repo.strip() or None
    shas = {r["git_sha"] for r in records if r["git_sha"]}
    dirty = any(r["git_dirty"] for r in records)
    if len(shas) > 1:
        return None
    if shas:
        return _flow({"repo": repo, "sha": shas.pop(), "dirty": dirty})
    if repo is None:
        return None
    try:
        info = code_sha(resolve_config_path(root, repo), exclude=root)
    except CodeError:
        return None
    return _flow({"repo": repo, "sha": info.sha, "dirty": dirty or info.dirty})


def _day(day: date) -> date:
    """A distinct `date` equal to `day`: ruamel writes a repeated object as a YAML alias."""
    return date(day.year, day.month, day.day)


def build_metrics(described: Sequence[Mapping[str, Any]], today: date) -> list[CommentedMap]:
    return [
        _flow(
            {
                "name": name,
                "value": d["headline"][name],
                "split": split_of(name),
                "run_id": d["run_id"],
                "as_of": _day(today),
            }
        )
        for d in described
        for name in sorted(d["headline"])
    ]


def render_results(metrics: Sequence[Mapping[str, Any]]) -> str:
    if not metrics:
        return "No headline metrics recorded.\n"
    lines = ["| metric | value | split | run |", "| --- | --- | --- | --- |"]
    for m in metrics:
        lines.append(
            f"| {escape_cell(m['name'])} | {json.dumps(m['value'])} | {m['split'] or '—'}"
            f" | {escape_cell(m['run_id'])} |"
        )
    return "\n".join(lines) + "\n"


SETUP_MARKER, RESULTS_MARKER = "setup", "results"


def marked(marker: str, block: str) -> str:
    """`block` between the comments that let a later `--into` find and replace it."""
    return f"<!-- labbrain:{marker} -->\n\n{block.strip(chr(10))}\n\n<!-- /labbrain:{marker} -->\n"


def _section_bounds(lines: Sequence[str], body_start: int, heading: str) -> tuple[int, int]:
    """(heading line index, index of the next level-2 heading or len) for `## heading`."""
    start, end, fence = None, len(lines), False
    for i in range(body_start, len(lines)):
        if lines[i].lstrip().startswith(FENCES):
            fence = not fence
            continue
        match = None if fence else H2_RE.match(lines[i].rstrip("\r\n"))
        if match is None:
            continue
        if start is not None:
            end = i
            break
        if match.group(1) == heading:
            start = i
    if start is None:
        raise RecordError(f"note has no ## {heading} section")
    return start, end


def _marked_block(
    lines: Sequence[str], start: int, end: int, marker: str
) -> tuple[int, int] | None:
    """(opening, closing) line indexes of the `marker` block in lines[start:end], if any."""
    opening, fence = None, False
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if stripped.startswith(FENCES):
            fence = not fence
        elif fence:
            continue
        elif opening is None and stripped == f"<!-- labbrain:{marker} -->":
            opening = i
        elif opening is not None and stripped == f"<!-- /labbrain:{marker} -->":
            return opening, i
    if opening is not None:
        raise ValueError(marker)
    return None


def append_to_section(text: str, heading: str, block: str, *, marker: str | None = None) -> str:
    """`text` with `block` added at the end of its `## heading` section, fences respected.

    With `marker`, a `marker` block already in the section (see `marked`) is replaced in
    place instead, so filling a note again leaves no stale block. Raises ValueError(marker)
    for an opening marker without its closing one.
    """
    _, _, body_line = split_frontmatter(text)
    lines = text.splitlines(keepends=True)
    start, end = _section_bounds(lines, body_line - 1, heading)
    newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
    rows = [row + newline for row in block.rstrip("\n").split("\n")]
    found = _marked_block(lines, start, end, marker) if marker else None
    if found is not None:
        opening, closing = found
        return "".join([*lines[:opening], *rows, *lines[closing + 1 :]])
    head = lines[:end]
    while len(head) - 1 > start and not head[-1].strip():
        head.pop()
    if not head[-1].endswith(("\n", "\r\n")):
        head[-1] += newline
    insertion = [newline, *rows]
    tail = lines[end:]
    if tail:
        insertion.append(newline)
    return "".join(head + insertion + tail)


def _fill(
    note: Note, label: str, fields: dict[str, Any], links: list[str], setup: str, results: str
) -> Path:
    """Write Setup/Results and update the frontmatter of `note` in one atomic write."""
    merged = list(dict.fromkeys([*note.get_list("links"), *links]))
    try:
        with open(note.path, "rb") as handle:
            text = handle.read().decode("utf-8")
    except UnicodeDecodeError:
        raise RecordError(f"{label}: note is not valid UTF-8") from None
    for heading, marker, block in (
        ("Setup", SETUP_MARKER, setup),
        ("Results", RESULTS_MARKER, results),
    ):
        try:
            text = append_to_section(text, heading, marked(marker, block), marker=marker)
        except ValueError:
            raise RecordError(
                f"{label}: the ## {heading} section has an unclosed labbrain:{marker} marker"
            ) from None
    try:
        updated = update_frontmatter_text(text, {**fields, "links": merged}, name=note.path.name)
    except ValueError:
        raise RecordError(f"{label}: frontmatter cannot be updated") from None
    atomic_write(note.path, updated if updated is not None else text)
    return note.path


def _check_line(flag: str, text: str) -> None:
    """Refuse one-line text that would start a heading or a code fence in the body."""
    if HEADING_RE.match(text):
        raise RecordError(f"{flag} must not be a heading")
    if text.startswith(FENCES):
        raise RecordError(f"{flag} must not start a code fence")


def record(
    root: Path, config: Config, req: RecordRequest, adapter: TrackerAdapter | None = None
) -> Path:
    """Create an experiment note from runs, or fill in a planned or running one."""
    from labbrain.trackers import check_run_ids, describe, get_adapter

    hypothesis = one_line(req.hypothesis or "")
    _check_line("--hypothesis", hypothesis)
    check_run_ids(req.run_ids)
    vault = Vault.load(root, config)
    for note_id in [req.parent, *req.links]:
        if note_id and vault.get(note_id) is None:
            raise RecordError(f"no note with ID {display_id(note_id, vault.notes)}")
    target = _fillable(vault, req.into) if req.into else None
    adapter = adapter or get_adapter(config, root)
    records = adapter.fetch(req.run_ids)
    described = [describe(r, config) for r in records]
    protocol = _resolve(
        req.protocol,
        target.get_str("protocol") if target else None,
        (d["protocol"] for d in described),
        "protocol",
    )
    dataset = _resolve(
        req.dataset,
        target.get_str("dataset") if target else None,
        (d["dataset"] for d in described),
        "dataset",
    )
    _require(vault, protocol, "protocol")
    _require(vault, dataset, "dataset")
    status = run_status(r["status"] for r in records)
    missing = [w for w, v in (("protocol", protocol), ("dataset", dataset)) if not v]
    if status == "done" and missing:
        keys = {
            "protocol": strip_controls(config.protocol_key),
            "dataset": strip_controls(config.dataset_key),
        }
        raise RecordError(
            f"{' and '.join(missing)} required to record finished runs: "
            f"pass {'/'.join('--' + w for w in missing)} "
            f"or set {'/'.join(keys[w] for w in missing)} in the run config"
        )
    hashes = {d["config_hash"] for d in described}
    url = next((r["url"] for r in records if r["url"]), None)
    today = req.now.date()
    metrics = build_metrics(described, today)
    fields: dict[str, Any] = {
        "updated": today,
        "status": status,
        "protocol": protocol,
        "tracker": _flow(
            {"backend": config.tracker.backend, "run_ids": list(req.run_ids), "url": url}
        ),
        "code": resolve_code(records, config, root),
        "config_hash": hashes.pop() if len(hashes) == 1 else None,
        "dataset": dataset,
        "metrics": metrics,
    }
    if hypothesis:
        fields["hypothesis"] = hypothesis
    if req.parent:
        parent = [r["config"] for r in adapter.fetch(parent_run_ids(vault, req.parent))]
        diff = config_diff(req.parent, parent, [r["config"] for r in records], config.hash_ignore)
        setup = render_setup(diff)
    else:
        _, varied = split_common([r["config"] for r in records], config.hash_ignore)
        setup = render_runs(req.run_ids, varied)
    results = render_results(metrics)
    links = list(dict.fromkeys(i for i in [req.parent, *req.links] if i))
    if target is not None:
        label = display_id(req.into or "", vault.notes)
        return _fill(target, label, fields, links, setup, results)
    return create(
        root,
        config,
        "experiment",
        title=req.title or "",
        author=req.author,
        now=req.now,
        links=links,
        summary=req.summary,
        extra=fields,
        section_text={
            "Hypothesis": hypothesis,
            "Setup": marked(SETUP_MARKER, setup),
            "Results": marked(RESULTS_MARKER, results),
        },
    )
