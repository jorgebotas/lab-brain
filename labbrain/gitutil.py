"""Thin wrapper over the git CLI for reading a base revision of the vault.

All paths returned are vault-relative, so a vault living in `brain/` inside a
code repository works and code changes outside the vault are ignored.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """A git command failed."""


@dataclass(frozen=True)
class Repo:
    top: Path
    prefix: str  # vault directory inside the repo, POSIX; "" when the vault is the repo root

    def git(self, *args: str, input: bytes | None = None) -> bytes:
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.top), *args], input=input, capture_output=True, check=True
            )
        except (OSError, subprocess.CalledProcessError) as exc:
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


def open_repo(vault_root: Path) -> Repo | None:
    """Both the toplevel and the prefix come from git, so a mis-cased path is canonicalised."""
    try:
        out = subprocess.run(
            ["git", "-C", str(vault_root), "rev-parse", "--show-toplevel", "--show-prefix"],
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
    return Repo(Path(lines[0]).resolve(), prefix)


def resolve_ref(repo: Repo, ref: str) -> str | None:
    try:
        sha = repo.git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()
    except GitError:
        return None
    return sha or None


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
