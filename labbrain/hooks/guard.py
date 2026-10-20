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
import unicodedata
from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase, translate
from pathlib import Path
from typing import Any

from labbrain.hooks import bash
from labbrain.hooks.paths import ProtectedRoot, canonical, fold
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

# A Glob component with any of these is a wildcard. `(` is added to the spec's `*?[{` so an
# extglob such as `@(name)` is not taken as a literal directory name.
GLOB_SPECIAL = frozenset("*?[{(")
# Remaining Glob syntax that fnmatch does not model: treated as able to reach anything below.
GLOB_UNMODELLED = ("**", "{", "(", "\\")

MAX_DEPTH = 20  # containers nested deeper than this in tool_input are not walked: deny
MAX_STRINGS = 2000  # more strings than this in tool_input: deny
MAX_STRING = 4096  # a path candidate is at most this long; the textual net sees it all
MAX_CANDIDATES = 5000  # more distinct path candidates than this in one call: deny

# Path-like substrings (Bash rule 1): runs containing `/`, `~` or `.`. Task 6 unifies this with
# bash.py. `findall` on it is quadratic on long runs without a delimiter, so the walk splits
# on `_DELIMITERS` and `fullmatch`es each token instead, which yields the same substrings.
PATHLIKE = re.compile(r"""[^\s'"`()<>;|&=,]*[/~.][^\s'"`()<>;|&=,]*""")
_DELIMITERS = re.compile(r"""[\s'"`()<>;|&=,]+""")
# A path-like token is also split here (R17), so a prefix stuck to a path (`file:../x`,
# `[../x]`) does not hide it; pieces with `/`, or starting with `~` or `.`, are candidates.
_STICKY = re.compile(r"[:\[\]{}@!$%^*+?]+")

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
    below it, so nothing is allowed.
    """
    value = payload.tool_input.get("file_path")
    if payload.tool_name != "Read" or not isinstance(value, str):
        return False
    try:
        path = canonical(value, payload.cwd)
    except (ValueError, RuntimeError, OSError):
        return False
    return any(v.root / ".labbrain" in path.parents for v in broken)


def _canon(value: object, base: Path) -> Path:
    """Canonical `value` joined to `base`; anything that cannot be canonicalised is unsure."""
    if not isinstance(value, str):
        raise _Unsure
    try:
        return canonical(value, base)
    except (ValueError, RuntimeError, OSError):
        raise _Unsure from None


def _check(payload: Payload, scope: Scope, subject: str) -> Denial | None:
    cwd = payload.cwd
    root = scope.targets.containing(_canon(str(cwd), cwd))
    if root is not None:
        return data_denial(root, CWD_SUBJECT)
    tool, args = payload.tool_name, payload.tool_input
    if tool in FILE_TOOLS:
        return _file_tool(tool, args, cwd, scope, subject)
    if tool == "Grep":
        return _grep(args, cwd, scope, subject)
    if tool == "Glob":
        return _glob(args, cwd, scope, subject)
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
    paths = [_canon(args[key], cwd) for key in PATH_KEYS if args.get(key) is not None]
    for path in paths:
        root = scope.targets.containing(path)
        if root is not None:
            return data_denial(root, subject)
    if tool in WRITE_TOOLS and any(scope.targets.is_guard_file(p) for p in paths):
        return Denial("guard-config", GUARD_CONFIG_MESSAGE)
    return None


def _start(args: dict[str, Any], cwd: Path) -> Path:
    """The canonical directory a Grep or Glob call starts from (`path`, default cwd)."""
    value = args.get("path")
    return _canon(str(cwd) if value is None or value == "" else value, cwd)


def _grep(args: dict[str, Any], cwd: Path, scope: Scope, subject: str) -> Denial | None:
    start = _start(args, cwd)
    root = scope.targets.containing(start)
    below = scope.targets.under(start)  # treated as rg: a recursive search enters them
    if root is not None or below:
        return data_denial(root or below[0], subject)
    glob = args.get("glob")
    if glob is not None:
        if not isinstance(glob, str):
            raise _Unsure
        root = _named(glob, _all_spellings(scope))
        if root is not None:
            return data_denial(root, subject)
    return None


def _glob(args: dict[str, Any], cwd: Path, scope: Scope, subject: str) -> Denial | None:
    """Glob is ripgrep (`rg --files --glob <pattern>` from `path`), with gitignore matching:
    a pattern with no `/` but a trailing one matches at any depth, and a leading `/` anchors
    it at the search root. Every reading the pattern may have is checked."""
    pattern = args.get("pattern")
    if not isinstance(pattern, str):
        raise _Unsure
    base = _start(args, cwd)
    expanded = _expand_home(_negations(pattern), scope.env)
    if os.sep not in expanded.rstrip(os.sep):
        readings = [base / "**" / expanded]  # matches at any depth below the search root
    elif expanded.startswith(os.sep):
        readings = [Path(expanded), base / expanded.lstrip(os.sep)]  # absolute, or anchored
    else:
        readings = [base / expanded]
    for reading in readings:
        root = _glob_reading(reading.parts, cwd, scope)
        if root is not None:
            return data_denial(root, subject)
    return None


def _negations(pattern: str) -> str:
    """`pattern` with each class opened by `[^` rewritten to `[!` (R18): globset negates with
    either, while fnmatch reads `[^x]` as the class of `^` and `x`."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        j = i + 1
        if pattern[i] == "[":
            j += pattern[j : j + 1] in ("!", "^")
            j += pattern[j : j + 1] == "]"  # a `]` first in a class is literal
            end = pattern.find("]", j)
            if end != -1:
                body = pattern[i + 1 : end]
                out.append("[" + ("!" + body[1:] if body.startswith("^") else body) + "]")
                i = end + 1
                continue
            j = i + 1
        out.append(pattern[i:j])
        i = j
    return "".join(out)


def _glob_reading(parts: tuple[str, ...], cwd: Path, scope: Scope) -> ProtectedRoot | None:
    """The root the absolute glob `parts` could match inside, or None."""
    cut = next((i for i, part in enumerate(parts) if GLOB_SPECIAL & set(part)), len(parts))
    prefix = _canon(str(Path(*parts[:cut])), cwd)
    rest = parts[cut:]
    if ".." in rest:  # a wildcard followed by `..` can climb anywhere
        raise _Unsure
    root = scope.targets.containing(prefix)
    if root is not None:
        return root
    for root in scope.targets.under(prefix):
        if _may_reach(rest, prefix, root):
            return root
    return None


def _may_reach(rest: tuple[str, ...], prefix: Path, root: ProtectedRoot) -> bool:
    """Whether the wildcard components `rest` below `prefix` could match inside `root`."""
    text = "/".join(rest)
    if any(token in text for token in GLOB_UNMODELLED):
        return True
    # `under` matched folded spellings, and folding keeps separators, so the root's first
    # components are the prefix's.
    names = root.path.parts[len(prefix.parts) :]
    if len(rest) < len(names):
        return False  # every match lies above the root
    return all(_component_matches(name, part) for name, part in zip(names, rest, strict=False))


def _component_matches(name: str, part: str) -> bool:
    """Whether Glob component `part` could match directory name `name`, over-approximated.

    Raw, folded, and case-insensitively in NFC and NFD: folding can change a name's length
    (ß -> ss), which breaks `?` and `[]`, and a name may be stored NFD on disk.
    """
    if fnmatchcase(name, part) or fnmatchcase(fold(name), fold(part)):
        return True
    forms = ("NFC", "NFD")
    names = {unicodedata.normalize(form, name) for form in forms}
    for pattern in {part, *(unicodedata.normalize(form, part) for form in forms)}:
        regex = re.compile(translate(pattern), re.IGNORECASE)
        if any(regex.fullmatch(n) for n in names):
            return True
    return False


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
    paths = [_canon(text[:MAX_STRING], cwd)]
    if len(text) > MAX_STRING:
        expanded = _expand_home(text, env)
        if os.sep not in expanded:
            return paths
        parts = [p for p in os.path.join(str(cwd), expanded).split(os.sep) if p not in ("", ".")]
        compact = os.sep + os.sep.join(parts)
        if ".." in parts or len(compact) > MAX_STRING:
            raise _Unsure
        paths.append(_canon(compact, cwd))
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
        for token in _DELIMITERS.split(text):
            if PATHLIKE.fullmatch(token):
                candidates.add(token)
                candidates.update(
                    piece
                    for piece in _STICKY.split(token)
                    if os.sep in piece or piece.startswith(("~", "."))
                )
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
