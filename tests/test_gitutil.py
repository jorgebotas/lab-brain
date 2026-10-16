from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from helpers import commit_all, git

from labbrain import gitutil


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "code"
    (repo / "brain" / "notes").mkdir(parents=True)
    (repo / "src.py").write_text("print('hi')\n")
    (repo / "brain" / "notes" / "a.md").write_text("one\n")
    (repo / "brain" / "notes" / "b.md").write_text("two\n")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo)
    return repo


def test_open_repo_reports_prefix(tmp_path: Path) -> None:
    repo_dir = make_repo(tmp_path)
    repo = gitutil.open_repo(repo_dir / "brain")
    assert repo is not None
    assert repo.top == repo_dir.resolve()
    assert repo.prefix == "brain"
    root_repo = gitutil.open_repo(repo_dir)
    assert root_repo is not None and root_repo.prefix == ""
    assert gitutil.open_repo(tmp_path) is None


def test_changed_files_tree_and_blobs_are_vault_relative(tmp_path: Path) -> None:
    repo_dir = make_repo(tmp_path)
    repo = gitutil.open_repo(repo_dir / "brain")
    assert repo is not None
    base = gitutil.resolve_ref(repo, "HEAD")
    assert base is not None and gitutil.resolve_ref(repo, "no-such-ref") is None
    (repo_dir / "src.py").write_text("print('changed')\n")
    (repo_dir / "brain" / "notes" / "a.md").write_text("one changed\n")
    (repo_dir / "brain" / "notes" / "b.md").unlink()
    assert gitutil.changed_files(repo, base) == [("M", "notes/a.md"), ("D", "notes/b.md")]
    tree = gitutil.ls_tree(repo, base)
    assert sorted(tree) == ["notes/a.md", "notes/b.md"]
    blobs = gitutil.read_blobs(repo, list(tree.values()))
    assert {blobs[tree["notes/a.md"]], blobs[tree["notes/b.md"]]} == {b"one\n", b"two\n"}


def test_open_repo_canonicalises_a_mis_cased_vault_path(tmp_path: Path) -> None:
    repo_dir = make_repo(tmp_path)
    mis_cased = repo_dir / "BRAIN"
    if not mis_cased.exists():
        pytest.skip("case-sensitive filesystem")
    repo = gitutil.open_repo(mis_cased)
    assert repo is not None
    assert repo.top == repo_dir.resolve()
    assert repo.prefix == "brain"
    base = gitutil.resolve_ref(repo, "HEAD")
    assert base is not None
    (repo_dir / "brain" / "notes" / "a.md").write_text("one changed\n")
    assert gitutil.changed_files(repo, base) == [("M", "notes/a.md")]


def test_resolve_ref_is_none_only_for_an_unknown_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_dir = make_repo(tmp_path)
    repo = gitutil.open_repo(repo_dir)
    assert repo is not None
    assert gitutil.resolve_ref(repo, "no-such-ref") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "main")
    empty_repo = gitutil.open_repo(empty)
    assert empty_repo is not None and gitutil.resolve_ref(empty_repo, "HEAD") is None

    def corrupt(*args: object, **kwargs: object) -> object:
        raise subprocess.CalledProcessError(128, ["git"], output=b"", stderr=b"fatal: corrupt")

    monkeypatch.setattr(gitutil.subprocess, "run", corrupt)
    with pytest.raises(gitutil.GitError):
        gitutil.resolve_ref(repo, "HEAD")
