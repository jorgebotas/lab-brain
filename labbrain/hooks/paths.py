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

import os
import unicodedata
from collections.abc import Sequence
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


def spellings(p: Path | str, base: Path | None = None) -> tuple[Path, ...]:
    """(canonical,) or, when the final component is a symlink, (canonical, own spelling).

    The own spelling is the path with every component but the last resolved, so it names
    the link itself. Errors propagate as for `canonical`.
    """
    path = _joined(p, base)
    full = path.resolve(strict=False)
    if path.name in ("", ".", ".."):
        return (full,)
    own = path.parent.resolve(strict=False) / path.name
    return (full,) if own == full else (full, own)


def fold(p: Path | str) -> str:
    """The comparison key for a path spelling: NFC-normalized, then casefolded."""
    return unicodedata.normalize("NFC", str(p)).casefold()


def _identity(path: Path | str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (st.st_dev, st.st_ino)


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

    def containing(self, p: Path) -> ProtectedRoot | None:
        """The root that `p` (under either spelling) is inside of or equal to, or None."""
        names = spellings(p)
        for candidate in names:
            for root in self.roots:
                for path in (root.path, root.link):
                    if path is not None and (candidate == path or path in candidate.parents):
                        return root
        for key in map(fold, names):
            for root_key, root in self._folded:
                if _within(key, root_key):
                    return root
        if self._ids:
            candidate = names[0]  # stat follows links: the own spelling has the same identity
            for part in (candidate, *candidate.parents):
                identity = _identity(part)
                if identity is not None and identity in self._ids:
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

    def is_guard_file(self, p: Path) -> bool:
        """Whether `p` (under either spelling) is a guard file, or lies in a guarded tree."""
        return any(
            _within(key, guard_key) if tree else key == guard_key
            for key in map(fold, spellings(p))
            for guard_key, tree in self._guard_folded
        )
