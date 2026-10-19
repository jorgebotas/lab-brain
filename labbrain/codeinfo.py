"""`labbrain code sha`: the code repository's commit, and whether it has uncommitted work.

When the vault lives inside the code repository, its own directory is left out of
the dirty check, so writing a note never makes the code look modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from labbrain import gitutil
from labbrain.errors import EngineError


class CodeError(EngineError):
    """The code repository cannot be read."""


@dataclass(frozen=True)
class CodeInfo:
    sha: str
    dirty: bool


def code_sha(repo_path: Path, *, exclude: Path | None = None) -> CodeInfo:
    repo = gitutil.open_repo(repo_path) if repo_path.is_dir() else None
    if repo is None:
        raise CodeError("not a git repository")
    try:
        sha = repo.git("rev-parse", "--verify", "HEAD").decode().strip()
    except gitutil.GitError:
        raise CodeError("the code repository has no commits") from None
    pathspec = ["."]
    # git itself places the vault (its toplevel and prefix are canonical, letter case
    # included), and the prefix is excluded literally: a vault named `v*` is no glob.
    vault = gitutil.open_repo(exclude) if exclude is not None and exclude.is_dir() else None
    if vault is not None and vault.top == repo.top and vault.prefix:
        pathspec.append(f":(exclude,literal){vault.prefix}")
    try:
        status = repo.git("status", "--porcelain", "--untracked-files=normal", "--", *pathspec)
    except gitutil.GitError:
        raise CodeError("git status failed in the code repository") from None
    return CodeInfo(sha, bool(status.strip()))
