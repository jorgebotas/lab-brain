"""PreToolUse write checks: the frozen-file guard and the PHI pre-write scan.

Both apply to Write, Edit, MultiEdit and NotebookEdit calls whose target lies in a vault
(the target's own vault, which need not be in the call's scope). The frozen-file guard runs
in every vault; the PHI scan only in a vault with `protected_data` on, for files in the PHI
scan scope. The proposed content is what the file would hold after the call: Write's
`content`, or the Edit / MultiEdit edits applied to the current file.

The frozen baseline is git HEAD, as in lint's frozen-edit rule, whose policy and comparison
this module shares (`labbrain.frozen`): a note written in this session stays editable until
it is committed. Paths are compared in their true on-disk case and casefolded, so
`Experiments/…` or `RAW/…` cannot slip past on a case-insensitive filesystem.

Heavy modules (git, notes, the frozen policy, PHI, the vault config) are imported only
once a write into a vault has been found.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from labbrain.hooks.paths import canonical, fold
from labbrain.hooks.payload import Denial, Payload, data_denial
from labbrain.hooks.scope import Scope, vault_of
from labbrain.layout import CONFIG_PATH, RAW_DIR, is_note_rel

if TYPE_CHECKING:
    from labbrain.frozen import Policy
    from labbrain.notes import Note
    from labbrain.vault import Config

WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
MANUSCRIPTS_DIR = "manuscripts"
PROPOSALS_DIR = "_proposals"

FROZEN_RULE = "frozen-file"
PHI_RULE = "phi"

_GUARD = "lab-brain frozen-file guard: "
FROZEN = (
    _GUARD + "{rel} is a frozen {type}; this edit is not allowed: {messages}. "
    "Supersede the note instead, or change only the allowed fields."
)
MANUSCRIPTS = (
    _GUARD + "manuscripts are edited through proposals; write under manuscripts/_proposals/ "
    "instead."
)
RAW = _GUARD + "raw/ files are immutable once written; add a new file instead."
CANNOT_APPLY = _GUARD + "could not apply this edit to a protected file; re-read the file and retry."
PHI = (
    "lab-brain PHI guard: the proposed content of {rel} matched {rules} (lines {lines}). "
    "Remove individual-level data before writing."
)

# C0 and C1 controls, DEL, and bidirectional formatting characters: never in a message.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f؜‎‏‪-‮⁦-⁩]+")


class _NotApplicable(Exception):
    """The proposed content cannot be computed (old_string missing, file unreadable, …)."""


# --- paths ------------------------------------------------------------------------------


def vault_rel(vault: Path, target: Path) -> str:
    """`target` (below `vault`) relative to `vault`, POSIX, in its true on-disk case.

    Each component is matched against its directory's entries: exactly if present, else
    by `fold`. From the first component that does not exist, the rest is kept as given.
    """
    parts = target.relative_to(vault).parts
    here, out = vault, []
    for index, part in enumerate(parts):
        try:
            names = os.listdir(here)
        except OSError:
            out.extend(parts[index:])
            break
        if part not in names:
            key = fold(part)
            matches = sorted(name for name in names if fold(name) == key)
            if not matches:
                out.extend(parts[index:])
                break
            part = matches[0]
        out.append(part)
        here = here / part
    return PurePosixPath(*out).as_posix()


def _folded_parts(rel: str) -> list[str]:
    return [fold(part) for part in PurePosixPath(rel).parts]


def is_raw(rel: str) -> bool:
    """Whether vault-relative `rel` lies under `raw/`, compared casefolded."""
    parts = _folded_parts(rel)
    return len(parts) >= 2 and parts[0] == RAW_DIR


def manuscript_outside_proposals(rel: str) -> bool:
    """Whether `rel` lies under `manuscripts/` but not under `manuscripts/_proposals/`."""
    parts = _folded_parts(rel)
    if not parts or parts[0] != MANUSCRIPTS_DIR:
        return False
    return not (len(parts) >= 3 and parts[1] == PROPOSALS_DIR)


def note_like(rel: str) -> bool:
    """Whether `rel` is a note location, as spelled or casefolded."""
    return is_note_rel(rel) or is_note_rel(fold(rel))


def _locations(raw: str, cwd: Path) -> tuple[Path, list[tuple[Path, str]]]:
    """The canonical target, and each (vault, true-case rel) it is reached through.

    The canonical path names the file actually written. The path as spelled (`..`
    collapsed, symlinks kept) is checked as well when it differs, so a symlinked
    `raw/` or `manuscripts/` directory is still guarded.
    """
    target = canonical(raw, cwd)
    found: list[tuple[Path, str]] = []
    vault = vault_of(target)
    if vault is not None:
        found.append((vault, vault_rel(vault, target)))
    spelled = Path(os.path.normpath(cwd / Path(raw).expanduser()))
    if spelled != target:
        for parent in spelled.parents:
            root = canonical(parent)
            if (root / CONFIG_PATH).is_file():
                location = (root, vault_rel(root, root / spelled.relative_to(parent)))
                if location not in found:
                    found.append(location)
                break
    return target, found


def _show(rel: str) -> str:
    return _CONTROL.sub("?", rel)


# --- proposed content -------------------------------------------------------------------


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _current_text(target: Path) -> str | None:
    """The file's text as notes are read (BOM dropped, LF endings); None if it is absent."""
    from labbrain.notes import decode_note

    if not os.path.lexists(target):
        return None
    try:
        return decode_note(target.read_bytes())
    except OSError:
        raise _NotApplicable from None


def _apply(text: str | None, edit: Any) -> str:
    """`text` (None: no file yet) after one Edit-shaped `edit`."""
    if not isinstance(edit, dict):
        raise _NotApplicable
    old, new, replace_all = edit.get("old_string"), edit.get("new_string"), edit.get("replace_all")
    if not isinstance(old, str) or not isinstance(new, str):
        raise _NotApplicable
    if replace_all is not None and not isinstance(replace_all, bool):
        raise _NotApplicable
    old, new = _lf(old), _lf(new)
    if old == "":
        if not text:  # creating the file, or filling an empty one
            return new
        raise _NotApplicable
    if text is None or old not in text:
        raise _NotApplicable
    return text.replace(old, new) if replace_all else text.replace(old, new, 1)


def proposed_content(payload: Payload, target: Path) -> str | None:
    """What `target` would hold after this call, or None when that cannot be computed."""
    tool_input = payload.tool_input
    if payload.tool_name == "Write":
        content = tool_input.get("content")
        return content if isinstance(content, str) else None
    if payload.tool_name == "Edit":
        edits: Any = [tool_input]
    elif payload.tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list) or not edits:
            return None
    else:  # NotebookEdit: a cell of a JSON document
        return None
    try:
        text = _current_text(target)
        for edit in edits:
            text = _apply(text, edit)
    except _NotApplicable:
        return None
    return text


def _new_strings(payload: Payload) -> str:
    """The text this call adds, for a PHI scan when the full content is unknown."""
    tool_input = payload.tool_input
    if payload.tool_name == "NotebookEdit":
        pieces: list[Any] = [tool_input.get("new_source")]
    elif payload.tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        edits = edits if isinstance(edits, list) else []
        pieces = [e.get("new_string") for e in edits if isinstance(e, dict)]
    elif payload.tool_name == "Edit":
        pieces = [tool_input.get("new_string")]
    else:
        pieces = [tool_input.get("content")]
    return "\n".join(piece for piece in pieces if isinstance(piece, str))


class _Proposed:
    """The proposed content, computed at most once and only when a check needs it."""

    def __init__(self, payload: Payload, target: Path) -> None:
        self._payload, self._target = payload, target
        self._done = False
        self._value: str | None = None

    def get(self) -> str | None:
        if not self._done:
            self._value, self._done = proposed_content(self._payload, self._target), True
        return self._value


# --- frozen notes -----------------------------------------------------------------------


def _base_rels(tree: dict[str, str], rel: str) -> list[str]:
    """HEAD note files for `rel`: by path, then by casefolded path, then by ID (stem)."""
    notes = [r for r in tree if is_note_rel(r)]
    if rel in notes:
        return [rel]
    key = fold(rel)
    by_path = [r for r in notes if fold(r) == key]
    if by_path:
        return by_path
    stem = fold(PurePosixPath(rel).stem)
    return [r for r in notes if fold(PurePosixPath(r).stem) == stem]


def frozen_bases(vault: Path, rel: str) -> list[tuple[Note, Policy]]:
    """The HEAD versions of the note at `rel` that are frozen, with their policies.

    Without a repository, or in one without commits, nothing is frozen. A git failure
    after the repository is opened raises (the hook then fails closed).
    """
    from labbrain import gitutil
    from labbrain.frozen import POLICIES, DoneProtocolsAtBase, frozen_at_base, parse_blob

    repo = gitutil.open_repo(vault)
    if repo is None:
        return []
    head = gitutil.resolve_ref(repo, "HEAD")
    if head is None:
        return []
    tree = gitutil.ls_tree(repo, head)
    rels = _base_rels(tree, rel)
    if not rels:
        return []
    blobs = gitutil.read_blobs(repo, [tree[r] for r in rels])
    done_protocols = DoneProtocolsAtBase(repo, tree)
    found = []
    for base_rel in rels:
        note = parse_blob(blobs[tree[base_rel]], base_rel)
        policy = POLICIES.get(note.type or "")
        if policy is not None and frozen_at_base(note, policy, done_protocols):
            found.append((note, policy))
    return found


def _frozen_denial(vault: Path, rel: str, proposed: _Proposed) -> Denial | None:
    if manuscript_outside_proposals(rel):
        return Denial(FROZEN_RULE, MANUSCRIPTS)
    if is_raw(rel) and os.path.lexists(vault / rel):
        return Denial(FROZEN_RULE, RAW)
    if not note_like(rel):
        return None
    bases = frozen_bases(vault, rel)
    if not bases:
        return None
    text = proposed.get()
    if text is None:
        return Denial(FROZEN_RULE, CANNOT_APPLY)
    from labbrain.frozen import compare
    from labbrain.notes import parse_note_text

    current = parse_note_text(text, Path(rel), rel)
    for base, policy in bases:
        messages = [finding.message for finding in compare(base, current, policy)]
        if messages:
            message = FROZEN.format(rel=_show(rel), type=base.type, messages="; ".join(messages))
            return Denial(FROZEN_RULE, message)
    return None


# --- PHI --------------------------------------------------------------------------------


def _config(scope: Scope, vault: Path) -> Config:
    """The vault's config: from the scope when loaded there, else loaded now (may raise)."""
    for info in scope.vaults:
        if info.root == vault and info.config is not None:
            return info.config
    from labbrain.vault import load_config

    return load_config(vault)


def _phi_denial(
    payload: Payload, scope: Scope, vault: Path, rel: str, proposed: _Proposed
) -> Denial | None:
    from labbrain.phi import ScanSettings, in_scan_scope, load_allowlist, scan_text

    if not in_scan_scope(rel):
        return None
    config = _config(scope, vault)
    if not config.protected_data:
        return None
    text = proposed.get()
    if text is None:
        text = _new_strings(payload)
    settings = ScanSettings.from_config(config, vault)
    allow = load_allowlist(vault)
    hits = [h for h in scan_text(text, settings) if (rel, h.rule, h.line_sha) not in allow]
    if not hits:
        return None
    rules = ", ".join(sorted({h.rule for h in hits}))
    lines = ", ".join(str(n) for n in sorted({h.line for h in hits}))
    return Denial(PHI_RULE, PHI.format(rel=_show(rel), rules=rules, lines=lines))


# --- entry ------------------------------------------------------------------------------


def check_write(payload: Payload, scope: Scope) -> Denial | None:
    """The denial for this write under the frozen-file guard or the PHI pre-scan, or None."""
    if payload.tool_name not in WRITE_TOOLS:
        return None
    key = "notebook_path" if payload.tool_name == "NotebookEdit" else "file_path"
    raw = payload.tool_input.get(key)
    if not isinstance(raw, str) or not raw:
        return None  # nothing to write to; the tool itself fails
    target, locations = _locations(raw, payload.cwd)
    if not locations:
        return None
    root = scope.targets.containing(target)
    if root is not None:  # the data guard's case; never name a file under a data path
        return data_denial(root, f"this {payload.tool_name} call")
    proposed = _Proposed(payload, target)
    for vault, rel in locations:
        denial = _frozen_denial(vault, rel, proposed)
        if denial is not None:
            return denial
    for vault, rel in locations:
        denial = _phi_denial(payload, scope, vault, rel, proposed)
        if denial is not None:
            return denial
    return None
