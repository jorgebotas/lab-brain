"""Thin wrapper over the git CLI for reading a base revision of the vault.

All paths returned are vault-relative, so a vault living in `brain/` inside a
code repository works and code changes outside the vault are ignored.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Final review item 9: what the hooks add to every git command they run, so a repository's
# own config cannot make a guard check start a program (an fsmonitor) or a git hook.
HOOK_GIT_OPTIONS: tuple[str, ...] = ("-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null")


class GitError(Exception):
    """A git command failed. `returncode` is git's exit status, None if git did not run."""

    def __init__(self, message: str, returncode: int | None = None) -> None:
        super().__init__(message)
        self.returncode = returncode


@dataclass(frozen=True)
class Repo:
    top: Path
    prefix: str  # vault directory inside the repo, POSIX; "" when the vault is the repo root
    options: tuple[str, ...] = ()  # global git options before every command (hooks only)

    def git(self, *args: str, input: bytes | None = None) -> bytes:
        argv = ["git", *self.options, "-C", str(self.top), *args]
        try:
            proc = subprocess.run(argv, input=input, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            raise GitError(f"git {args[0]} failed", exc.returncode) from exc
        except OSError as exc:
            raise GitError(f"git {args[0]} failed") from exc
        return proc.stdout

    @property
    def pathspec(self) -> str:
        return self.prefix or "."

    def to_vault_rel(self, repo_rel: str) -> str | None:
        if not self.prefix:
            return repo_rel
        head = self.prefix + "/"
        return repo_rel[len(head) :] if repo_rel.startswith(head) else None


def open_repo(vault_root: Path, *, hook: bool = False) -> Repo | None:
    """Both the toplevel and the prefix come from git, so a mis-cased path is canonicalised.
    With `hook`, this and every later command of the repo run with HOOK_GIT_OPTIONS."""
    options = HOOK_GIT_OPTIONS if hook else ()
    try:
        out = subprocess.run(
            [
                "git",
                *options,
                "-C",
                str(vault_root),
                "rev-parse",
                "--show-toplevel",
                "--show-prefix",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    lines = out.split("\n")
    if not lines[0]:
        return None
    prefix = lines[1].rstrip("/") if len(lines) > 1 else ""
    return Repo(Path(lines[0]).resolve(), prefix, options)


def resolve_ref(repo: Repo, ref: str) -> str | None:
    """The commit SHA `ref` names, or None if it names no commit (including HEAD in a
    repository without commits). Any other git failure raises GitError."""
    try:
        sha = repo.git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()
    except GitError as exc:
        # --verify --quiet exits 1, silently, exactly when the revision does not resolve.
        if exc.returncode == 1 and not _stderr(exc):
            return None
        raise
    return sha or None


def _stderr(exc: GitError) -> bytes:
    cause = exc.__cause__
    if isinstance(cause, subprocess.CalledProcessError):
        return cause.stderr or b""
    return b""


def changed_files(repo: Repo, base: str) -> list[tuple[str, str]]:
    """(status letter, vault-relative path) for tracked files that differ from base."""
    raw = repo.git("diff", "--name-status", "--no-renames", "-z", base, "--", repo.pathspec)
    fields = raw.decode("utf-8", "replace").split("\0")
    result = []
    for status, path in zip(fields[0::2], fields[1::2], strict=False):
        rel = repo.to_vault_rel(path) if status else None
        if rel is not None:
            result.append((status[0], rel))
    return result


def ls_tree(repo: Repo, base: str) -> dict[str, str]:
    """Vault-relative path → blob SHA for every file at base."""
    raw = repo.git("ls-tree", "-r", "-z", base, "--", repo.pathspec).decode("utf-8", "replace")
    tree = {}
    for entry in raw.split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        _mode, kind, sha = meta.split()
        rel = repo.to_vault_rel(path)
        if kind == "blob" and rel is not None:
            tree[rel] = sha
    return tree


def read_blobs(repo: Repo, shas: Iterable[str]) -> dict[str, bytes]:
    """Read many blobs through a single `git cat-file --batch` process."""
    unique = sorted(set(shas))
    if not unique:
        return {}
    out = repo.git("cat-file", "--batch", input=("\n".join(unique) + "\n").encode())
    blobs: dict[str, bytes] = {}
    pos = 0
    for _ in unique:
        newline = out.index(b"\n", pos)
        sha, _kind, size = out[pos:newline].decode().split()
        start = newline + 1
        blobs[sha] = out[start : start + int(size)]
        pos = start + int(size) + 1
    return blobs
