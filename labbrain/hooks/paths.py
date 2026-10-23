"""Canonical paths and containment in protected roots. Standard library only.

Containment over-approximates on purpose: a candidate is inside a root when its canonical
path starts with the root's, when the NFC-normalized casefolded spellings do (so `/Data`
matches `/data` even on a case-sensitive filesystem), or when the candidate or one of its
parents is the same directory as the root by `(st_dev, st_ino)`. A root that does not exist
is still matched by text; only the identity check needs it on disk.

A path whose final component is a symlink has two spellings: the canonical one (the link's
target) and its own (the link itself, its parent resolved). Roots, guard files and
candidates are compared under both, so a guard file reached through a link is guarded at
its target, and a link inside a root or guarded tree counts as inside even when it points
elsewhere: rewriting or removing it changes that tree.
"""

from __future__ import annotations

import errno
import os
import re
import stat
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path


def _joined(p: Path | str, base: Path | None) -> Path:
    """`p` with a leading `~` or `~user` expanded, then joined to `base` when relative.

    Ruling R15: an unknown `~user` is left as written, a relative name, as the shell leaves
    it. A NUL byte raises `ValueError`.
    """
    path = Path(os.path.expanduser(os.fspath(p)))
    if not path.is_absolute() and base is not None:
        path = base / path
    return path


def canonical(p: Path | str, base: Path | None = None) -> Path:
    """`p` with `~` expanded, joined to `base` when relative, and resolved (symlinks, `..`).

    The path need not exist. An unknown `~user` is a relative name (R15). Errors (a NUL
    byte, a symlink loop) are left to the caller: on the PreToolUse path they deny.
    """
    return _joined(p, base).resolve(strict=False)


def readings(p: Path | str, base: Path | None = None) -> list[Path]:
    """Ruling R22: the paths `p`, joined to `base` when relative, may name.

    The physical reading (`canonical`) resolves each link before climbing a `..`, as the
    system does; it comes first and is never dropped. The textual reading collapses `..`
    first, as Claude Code's Node `path.resolve` and a logical `cd` do, and is then
    canonicalised; it is only ever an extra check, returned when it differs. Errors
    propagate as for `canonical`.
    """
    joined = _joined(p, base)
    physical = joined.resolve(strict=False)
    collapsed = os.path.normpath(joined)
    if collapsed == str(joined):  # no `..` to collapse: the same text, the same reading
        return [physical]
    textual = canonical(collapsed)
    return [physical] if textual == physical else [physical, textual]


def spellings(p: Path | str, base: Path | None = None) -> tuple[Path, ...]:
    """(canonical,) or, when the final component is a symlink, (canonical, own spelling).

    The own spelling is the path with every component but the last resolved, so it names
    the link itself. Errors propagate as for `canonical`.
    """
    path = _joined(p, base)
    if path.name in ("", ".", ".."):
        return (path.resolve(strict=False),)
    own = path.parent.resolve(strict=False) / path.name
    # Resolving `path` resolves its parent, then looks at the last component: unless that
    # is a link, the canonical spelling is `own`, and a second full resolution is saved.
    if not _is_link(own):
        return (own,)
    full = path.resolve(strict=False)
    return (full,) if own == full else (full, own)


def _is_link(path: Path) -> bool:
    """Whether `path` itself is a symlink; a path that cannot be looked at is not one, as
    for `os.path.realpath`."""
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


# Path candidates in free text, shared by Bash rule 1 and the generic tool walk: runs free
# of PATH_DELIMITERS that hold one of PATH_CHARS. Text is split, never matched with a
# backtracking regex (`findall` is quadratic on long undelimited text); PATHLIKE is the same
# set of runs as one regex.
PATH_DELIMITERS = re.compile(r"""[\s'"`()<>;|&=,]+""")
PATH_CHARS = frozenset("/~.")
PATHLIKE = re.compile(r"""[^\s'"`()<>;|&=,]*[/~.][^\s'"`()<>;|&=,]*""")
# Ruling R17: a path-like run is also split here, so a prefix stuck to a path (`file:../x`,
# `[../x]`) does not hide it.
STICKY = re.compile(r"[:\[\]{}@!$%^*+?]+")


# Ruling R36 for free text (final review item 3): PATH_DELIMITERS splits at `=` and `,`, and
# STICKY at `:`, but a root may hold them (`run=1`, a Hive partition). So a run split only
# at LOOSE_DELIMITERS is a candidate too when it holds `=` or `,`, and so is the text after
# each `=`, `,` or `:` in it. A suffix longer than SUFFIX_LIMIT cannot be opened as a path
# (PATH_MAX, plus what a `~user` prefix can shed), so only the last ones are built.
LOOSE_DELIMITERS = re.compile(r"""[\s'"`()<>;|&]+""")
SUFFIX_MARKS = re.compile(r"[=,:]")
SUFFIX_LIMIT = 4096 + 256
SUFFIX_BUDGET = 32 * 1024 * 1024


def path_like(token: str) -> bool:
    """Whether `token` (free of PATH_DELIMITERS) holds `/`, `~` or `.`."""
    return not PATH_CHARS.isdisjoint(token)


def path_runs(text: str) -> Iterator[str]:
    """The path-like runs of `text`, in order: what PATHLIKE finds, in linear time."""
    for run in PATH_DELIMITERS.split(text):
        if path_like(run):
            yield run


def loose_runs(text: str) -> Iterator[str]:
    """The path-like runs of `text` split only at LOOSE_DELIMITERS that hold `=` or `,`:
    the runs `path_runs` would cut there (R36)."""
    for run in LOOSE_DELIMITERS.split(text):
        if ("=" in run or "," in run) and path_like(run):
            yield run


class TextTooLarge(Exception):
    """A call's `Budget` of suffix text ran out; the caller denies (input too large)."""


class Budget:
    """The characters of suffix text one hook call may build (SUFFIX_BUDGET): each run's
    suffixes are bounded, but text can repeat one run many times."""

    def __init__(self, limit: int = 0) -> None:
        self.left = limit or SUFFIX_BUDGET

    def __repr__(self) -> str:
        return f"Budget(left={self.left})"

    def spend(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise TextTooLarge


def suffixes(run: str, budget: Budget) -> Iterator[str]:
    """The text after each `=`, `,` or `:` of `run`, within its last SUFFIX_LIMIT characters
    (R36), spending `budget`."""
    for mark in SUFFIX_MARKS.finditer(run, max(0, len(run) - SUFFIX_LIMIT - 1)):
        budget.spend(len(run) - mark.end())
        yield run[mark.end() :]


def joined_runs(text: str, budget: Budget) -> Iterator[str]:
    """R36's extra candidates in free text: each run of `loose_runs`, and the path-like
    `suffixes` of every path-like run split only at LOOSE_DELIMITERS, in order."""
    for run in LOOSE_DELIMITERS.split(text):
        if not path_like(run):
            continue
        if "=" in run or "," in run:
            yield run
        yield from filter(path_like, suffixes(run, budget))


def sticky_pieces(token: str) -> list[str]:
    """The pieces of `token` split at STICKY that are candidates: with `/`, or starting
    with `~` or `.` (R17)."""
    return [piece for piece in STICKY.split(token) if "/" in piece or piece.startswith(("~", "."))]


def fold(p: Path | str) -> str:
    """The comparison key for a path spelling: NFC-normalized, casefolded, and NFC-normalized
    again, because casefolding can decompose (U+01F0 folds to j + U+030C)."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", str(p)).casefold())


def _identity(path: Path | str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (st.st_dev, st.st_ino)


# Errors of looking up P that every path below P fails with too.
_ABSENT = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ENAMETOOLONG})


def _absent(path: Path) -> bool:
    """Whether `path` cannot be looked up, so that nothing below it can be either."""
    try:
        os.lstat(path)
    except OSError as error:
        return error.errno in _ABSENT
    except ValueError:
        return True  # a NUL byte: every path below holds it too
    return False


def _identities(path: Path) -> list[tuple[int, int]]:
    """The `_identity` of `path`'s ancestors and of `path`, from the top down. Below one
    that is absent, no deeper one is looked at (a long candidate has many parts, and a
    command can have thousands of candidates)."""
    found: list[tuple[int, int]] = []
    for part in (*reversed(path.parents), path):
        identity = _identity(part)
        if identity is not None:
            found.append(identity)
        elif _absent(part):
            break
    return found


def _below_or_at(candidate: Path, path: Path) -> bool:
    """`candidate == path or path in candidate.parents`, for absolute paths, by text."""
    c, r = str(candidate), str(path)
    return c == r or c.startswith(r if r.endswith(os.sep) else r + os.sep)


def _within(key: str, root_key: str) -> bool:
    """Whether folded `key` equals folded `root_key` or lies below it."""
    return key == root_key or key.startswith(root_key.rstrip(os.sep) + os.sep)


@dataclass(frozen=True)
class ProtectedRoot:
    """One `data_paths` entry of one vault.

    `index` is the entry's 1-based position in that vault's `data_paths`, `configured` the
    entry exactly as written, and `path` its canonical form. When the entry itself is a
    symlink, `link` is its own spelling (see `spellings`); otherwise it is None.
    """

    vault: Path
    index: int
    configured: str
    path: Path
    link: Path | None = None


@dataclass(frozen=True)
class GuardFile:
    """A file the guard's own configuration lives in; `tree` covers everything below too."""

    path: Path
    tree: bool


class Targets:
    """The protected roots and guard files of a hook call's scope."""

    def __init__(self, roots: Sequence[ProtectedRoot], guard_files: Sequence[GuardFile]) -> None:
        self.roots: tuple[ProtectedRoot, ...] = tuple(roots)
        self.guard_files: tuple[GuardFile, ...] = tuple(guard_files)
        self._folded = [
            (fold(path), r) for r in self.roots for path in (r.path, r.link) if path is not None
        ]
        self._ids: dict[tuple[int, int], ProtectedRoot] = {}
        for root in self.roots:
            identity = _identity(root.path)
            if identity is not None:
                self._ids.setdefault(identity, root)
        self._guard_folded = [(fold(g.path), g.tree) for g in self.guard_files]

    def __repr__(self) -> str:
        return f"Targets(roots={len(self.roots)}, guard_files={len(self.guard_files)})"

    def containing(self, p: Path, names: Sequence[Path] = ()) -> ProtectedRoot | None:
        """The root that `p` (under either spelling) is inside of or equal to, or None.
        `names`, when given, is `spellings(p)` already computed."""
        names = names or spellings(p)
        for candidate in names:
            for root in self.roots:
                for path in (root.path, root.link):
                    if path is not None and _below_or_at(candidate, path):
                        return root
        for key in map(fold, names):
            for root_key, root in self._folded:
                if _within(key, root_key):
                    return root
        if self._ids:
            candidate = names[0]  # stat follows links: the own spelling has the same identity
            for identity in reversed(_identities(candidate)):  # the deepest first
                if identity in self._ids:
                    return self._ids[identity]
        return None

    def under(self, p: Path) -> list[ProtectedRoot]:
        """The roots strictly below `p` (a recursive walk from `p` reaches them), each once,
        in configured order. Both spellings of `p` and of each root count."""
        keys = [fold(name) for name in spellings(p)]
        found = {
            id(r): r
            for root_key, r in self._folded
            for key in keys
            if root_key != key and _within(root_key, key)
        }
        return [r for r in self.roots if id(r) in found]

    def is_guard_file(self, p: Path, names: Sequence[Path] = ()) -> bool:
        """Whether `p` (under either spelling) is a guard file, or lies in a guarded tree.
        `names`, when given, is `spellings(p)` already computed."""
        return any(
            _within(key, guard_key) if tree else key == guard_key
            for key in map(fold, names or spellings(p))
            for guard_key, tree in self._guard_folded
        )
