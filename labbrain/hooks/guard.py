"""The data guard and guard self-protection for PreToolUse (spec sections 4 and 5).

`check_tool` decides, in this order: an unprotected scope allows everything; a broken vault
config denies everything except a Read of that vault's own `.labbrain/` files; a session cwd
inside a protected root denies everything; then each tool is judged by the paths it names.
Every check over-approximates: a candidate the guard cannot judge with confidence denies.
Messages never quote a candidate path, a file name or file contents.
"""

from __future__ import annotations

import os
import pwd
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from labbrain.hooks import bash
from labbrain.hooks.exposure import links_under
from labbrain.hooks.paths import PATHLIKE as PATHLIKE  # re-exported for callers of guard
from labbrain.hooks.paths import ProtectedRoot, fold, path_runs, readings, sticky_pieces
from labbrain.hooks.paths import canonical as canonical  # re-exported for callers of guard
from labbrain.hooks.payload import Denial, Payload, data_denial
from labbrain.hooks.scope import Scope, VaultInfo

SKIP_TOOLS: frozenset[str] = frozenset(
    {
        "Agent",
        "Task",
        "TodoWrite",
        "ToolSearch",
        "Skill",
        "AskUserQuestion",
        "WebSearch",
        "ExitPlanMode",
        "EnterPlanMode",
        "SendMessage",
        "TaskStop",
        "ScheduleWakeup",
    }
)
FILE_TOOLS = frozenset({"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "NotebookRead", "LS"})
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
PATH_KEYS = ("file_path", "notebook_path", "path")

# A Glob component with any of these is a wildcard (R20): the literal directories before it
# are where the search may start. A component starting with `!`, or any `\\`, denies.
GLOB_SPECIAL = frozenset("*?[]{}!\\")
# Claude Code's own cut (GKo): its search starts at the last `/` before the first of these.
GKO_SPECIAL = frozenset("*?[{")
MAX_GLOB_NAMES = 16  # more literal leading directories than this in a Glob pattern: deny (R23)

MAX_DEPTH = 20  # containers nested deeper than this in tool_input are not walked: deny
MAX_STRINGS = 2000  # more strings than this in tool_input: deny
MAX_STRING = 4096  # a path candidate is at most this long; the textual net sees it all
MAX_CANDIDATES = 5000  # more distinct path candidates than this in one call: deny

# A tool name goes into the message: anything outside this set is replaced, length capped.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_.:-]+")
MAX_NAME = 128

CWD_SUBJECT = "this session's working directory"
BROKEN_CONFIG_MESSAGE = (
    "lab-brain guard: this vault's .labbrain/config.yaml could not be loaded, so protected "
    "data paths are unknown and every tool call is blocked. Ask the user to fix "
    ".labbrain/config.yaml (labbrain lint shows the problem)."
)
GUARD_CONFIG_MESSAGE = (
    "lab-brain guard: agents may not change lab-brain or Claude Code guard settings in a "
    "protected vault. Ask the user to make this change."
)


class _Unsure(Exception):
    """A candidate the guard cannot judge with confidence; the call is denied."""


def check_tool(payload: Payload, scope: Scope) -> Denial | None:
    """The denial for this tool call under the data guard and self-protection, or None."""
    if not scope.protected:
        return None
    if scope.broken and not _reads_broken_config(payload, scope.broken):
        return Denial("config", BROKEN_CONFIG_MESSAGE)
    name = _UNSAFE_NAME.sub("_", payload.tool_name)[:MAX_NAME] or "tool"
    subject = f"this {name} call"
    try:
        return _check(payload, scope, subject)
    except _Unsure:
        roots = scope.targets.roots
        # No known root means the scope is protected only by a broken vault.
        return data_denial(roots[0], subject) if roots else Denial("config", BROKEN_CONFIG_MESSAGE)


def _reads_broken_config(payload: Payload, broken: Iterable[VaultInfo]) -> bool:
    """Whether this is a Read of a file inside a broken vault's own `.labbrain/`.

    The directory is not resolved: when `.labbrain` is itself a link, no resolved path lies
    below it, so nothing is allowed. Both readings (R22) must lie below it.
    """
    value = payload.tool_input.get("file_path")
    if payload.tool_name != "Read" or not isinstance(value, str):
        return False
    try:
        paths = _readings(value, payload.cwd)
    except _Unsure:
        return False
    return all(any(v.root / ".labbrain" in path.parents for v in broken) for path in paths)


def _readings(value: object, base: Path) -> list[Path]:
    """`paths.readings` of `value` against `base` (R22); a value that is not a string, or
    cannot be canonicalised, is unsure."""
    if not isinstance(value, str):
        raise _Unsure
    try:
        return readings(value, base)
    except (ValueError, RuntimeError, OSError):
        raise _Unsure from None


def _reach(paths: Iterable[Path], scope: Scope) -> ProtectedRoot | None:
    """The root one of `paths` lies inside, or that a recursive walk from one reaches."""
    for path in paths:
        root = scope.targets.containing(path)
        below = scope.targets.under(path)
        if root is not None or below:
            return root or below[0]
    return None


def _check(payload: Payload, scope: Scope, subject: str) -> Denial | None:
    cwd = payload.cwd
    for path in _readings(str(cwd), cwd):
        root = scope.targets.containing(path)
        if root is not None:
            return data_denial(root, CWD_SUBJECT)
    tool, args = payload.tool_name, payload.tool_input
    if tool in FILE_TOOLS:
        return _file_tool(tool, args, cwd, scope, subject)
    if tool == "Grep":
        return _grep(args, cwd, scope, subject, payload.session_id)
    if tool == "Glob":
        return _glob(args, cwd, scope, subject, payload.session_id)
    if tool == "Bash":
        command = args.get("command")
        if not isinstance(command, str):
            raise _Unsure
        return bash.check_command(
            command, payload.cwd, scope, env=scope.env, session_id=payload.session_id
        )
    if tool in SKIP_TOOLS:
        return None
    return _any_tool(args, cwd, scope, subject)


def _file_tool(
    tool: str, args: dict[str, Any], cwd: Path, scope: Scope, subject: str
) -> Denial | None:
    paths = [p for key in PATH_KEYS if args.get(key) is not None for p in _readings(args[key], cwd)]
    for path in paths:
        root = scope.targets.containing(path)
        if root is not None:
            return data_denial(root, subject)
    if tool in WRITE_TOOLS and any(scope.targets.is_guard_file(p) for p in paths):
        return Denial("guard-config", GUARD_CONFIG_MESSAGE)
    return None


def _start(args: dict[str, Any], cwd: Path) -> list[Path]:
    """The readings of the directory a Grep or Glob call starts from (`path`, default cwd)."""
    value = args.get("path")
    return _readings(str(cwd) if value is None or value == "" else value, cwd)


def _exposed(bases: Iterable[Path], scope: Scope, session_id: str) -> bool:
    """R10: whether a link below one of the directories `bases` leads into a protected root
    (Bash rule 6b's walk, cached the same way). A truncated walk is unsure."""
    data = scope.env.get("CLAUDE_PLUGIN_DATA")
    cache = Path(data) if data else None
    for base in dict.fromkeys(bases):
        if not base.is_dir():
            continue
        scan = links_under(base, scope.targets, cache, session_id)
        if scan.truncated:
            raise _Unsure
        if scan.found:
            return True
    return False


def _grep(
    args: dict[str, Any], cwd: Path, scope: Scope, subject: str, session_id: str
) -> Denial | None:
    starts = _start(args, cwd)
    root = _reach(starts, scope)  # treated as rg: a recursive search enters roots
    if root is not None:
        return data_denial(root, subject)
    if _exposed(starts, scope, session_id):
        return data_denial(scope.targets.roots[0], subject)
    glob = args.get("glob")
    if glob is not None:
        if not isinstance(glob, str):
            raise _Unsure
        root = _named(glob, _all_spellings(scope))
        if root is not None:
            return data_denial(root, subject)
    return None


def _glob(
    args: dict[str, Any], cwd: Path, scope: Scope, subject: str, session_id: str
) -> Denial | None:
    """Glob is a recursive construct (R20), like rule 6a for Bash.

    Claude Code rewrites a pattern before ripgrep runs it, so the pattern is not matched. It
    is denied when any directory it may search from holds a protected root or lies inside
    one, or holds a link into one (R10), or when ripgrep could read it as an exclusion
    (`!`) or an escape (`\\`).
    """
    pattern = args.get("pattern")
    if not isinstance(pattern, str):
        raise _Unsure
    bases = _glob_bases(pattern, _start(args, cwd), scope.env)
    paths = [path for base in bases for path in _readings(str(base), cwd)]
    root = _reach(paths, scope)
    if root is None and _exposed(paths, scope, session_id):
        root = scope.targets.roots[0]
    return None if root is None else data_denial(root, subject)


def _glob_bases(pattern: str, starts: list[Path], env: Mapping[str, str]) -> list[Path]:
    """Every directory a Glob of `pattern` from `starts` (the readings of `path`) may search.

    `starts` and, for an absolute or `~` pattern, where Claude Code starts ripgrep (R21): the
    deepest literal directory before the first wildcard component, or for a fully literal
    pattern its parent and the path itself. That is taken at the guard's cut and at Claude
    Code's narrower GKo cut (R22). Each run of the pattern's literal leading directories is
    also joined to every such base (the pattern read relative, `/`-anchored, or with leading
    components that repeat the end of `path` stripped).
    """
    parts = pattern.split(os.sep)
    if "\\" in pattern or any(part.startswith("!") for part in parts):
        raise _Unsure
    cuts = [_cut(parts, GLOB_SPECIAL), _cut(parts, GKO_SPECIAL)]
    if ".." in parts[cuts[0] :]:  # a wildcard followed by `..` can climb anywhere
        raise _Unsure
    names = [part for part in parts[: cuts[1]] if part not in ("", ".")]
    if len(names) > MAX_GLOB_NAMES:
        raise _Unsure
    anchors = list(starts)
    if pattern.startswith((os.sep, "~")):
        for cut in cuts:
            prefix = Path(_expand_home(os.sep.join(parts[:cut]) or os.sep, env))
            anchors += [prefix.parent, prefix] if cut == len(parts) else [prefix]
    runs = [names[i:j] for i in range(len(names)) for j in range(i + 1, len(names) + 1)]
    bases = {str(anchor): anchor for anchor in anchors}
    for anchor in anchors:
        for run in runs:
            base = anchor.joinpath(*run)
            bases.setdefault(str(base), base)
    return list(bases.values())


def _cut(parts: list[str], special: frozenset[str]) -> int:
    """The index of the first component of `parts` holding a character in `special`."""
    return next((i for i, part in enumerate(parts) if special & set(part)), len(parts))


def _expand_home(text: str, env: Mapping[str, str]) -> str:
    """`text` with a leading `~` expanded from the hook's HOME (R1), or `~user` from the user
    database; unknown users are unsure."""
    if not text.startswith("~"):
        return text
    head, sep, tail = text.partition(os.sep)
    try:
        if head == "~":
            home = env.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir
        else:
            home = pwd.getpwnam(head[1:]).pw_dir
    except KeyError:
        raise _Unsure from None
    return home + sep + tail


def _spellings(root: ProtectedRoot, scope: Scope) -> set[str]:
    """The folded spellings of `root` the textual net looks for: configured, `~`-expanded
    (with the hook's HOME, or the user database for `~user`) and canonical."""
    configured = root.configured.strip()
    found = {configured, str(root.path), _expand_home(configured, scope.env)}
    return {fold(s.rstrip(os.sep) or s) for s in found if s}


Spellings = list[tuple[ProtectedRoot, set[str]]]


def _all_spellings(scope: Scope) -> Spellings:
    return [(root, _spellings(root, scope)) for root in scope.targets.roots]


def _named(text: str, spellings: Spellings) -> ProtectedRoot | None:
    """The root one of whose spellings occurs in `text`, compared folded."""
    key = fold(text)
    for root, names in spellings:
        if any(name in key for name in names):
            return root
    return None


def _strings(tool_input: dict[str, Any]) -> list[str]:
    """Every string in `tool_input`, keys included; past the caps the call is unsure."""
    found: list[str] = []
    stack: list[tuple[Any, int]] = [(tool_input, 0)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, str):
            found.append(value)
            if len(found) > MAX_STRINGS:
                raise _Unsure
        elif isinstance(value, dict | list):
            if depth > MAX_DEPTH:
                raise _Unsure
            items = [x for kv in value.items() for x in kv] if isinstance(value, dict) else value
            stack.extend((item, depth + 1) for item in items)
    return found


def _paths(text: str, cwd: Path, env: Mapping[str, str]) -> list[Path]:
    """The canonical paths candidate `text` may name.

    A candidate over the cap is checked truncated and also in full, joined to cwd with only
    `.` and empty components removed (so `./` padding cannot push a path past the cap). `..`
    is never collapsed as text, because the system resolves a link before climbing from it:
    a long candidate with a `..` component, or still over the cap, is unsure. A long single
    component, with no separator, cannot name a file and needs nothing more.
    """
    paths = _readings(text[:MAX_STRING], cwd)
    if len(text) > MAX_STRING:
        expanded = _expand_home(text, env)
        if os.sep not in expanded:
            return paths
        parts = [p for p in os.path.join(str(cwd), expanded).split(os.sep) if p not in ("", ".")]
        compact = os.sep + os.sep.join(parts)
        if ".." in parts or len(compact) > MAX_STRING:
            raise _Unsure
        paths += _readings(compact, cwd)
    return paths


def _any_tool(args: dict[str, Any], cwd: Path, scope: Scope, subject: str) -> Denial | None:
    """Every string, and every path-like substring of one, is a path candidate; every string
    is searched for a root's spelling. A candidate that is a guard file denies (R11)."""
    spellings = _all_spellings(scope)
    candidates: set[str] = set()
    for text in _strings(args):
        root = _named(text, spellings)
        if root is not None:
            return data_denial(root, subject)
        candidates.add(text)
        for token in path_runs(text):
            candidates.add(token)
            candidates.update(sticky_pieces(token))
        if len(candidates) > MAX_CANDIDATES:
            raise _Unsure
    paths = [path for text in candidates for path in _paths(text, cwd, scope.env)]
    for path in paths:
        root = scope.targets.containing(path)
        if root is not None:
            return data_denial(root, subject)
    if any(scope.targets.is_guard_file(path) for path in paths):
        return Denial("guard-config", GUARD_CONFIG_MESSAGE)
    return None
