from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

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


def _fake_toplevel(monkeypatch: pytest.MonkeyPatch, toplevel: Path) -> None:
    real_run = subprocess.run

    def run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
        proc = real_run(cmd, *args, **kwargs)
        if cmd[-1] == "--show-toplevel":
            proc.stdout = f"{toplevel}\n"
        return proc

    monkeypatch.setattr(gitutil.subprocess, "run", run)


def test_open_repo_relates_differently_cased_toplevel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_dir = make_repo(tmp_path)
    recased = repo_dir.parent / repo_dir.name.upper()
    _fake_toplevel(monkeypatch, recased)
    repo = gitutil.open_repo(repo_dir / "brain")
    if recased.exists():  # case-insensitive filesystem: the same directory
        assert repo is not None and repo.prefix == "brain"
        assert gitutil.resolve_ref(repo, "HEAD") is not None
    else:
        assert repo is None


def test_open_repo_returns_none_for_unrelated_toplevel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_dir = make_repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _fake_toplevel(monkeypatch, elsewhere)
    assert gitutil.open_repo(repo_dir / "brain") is None
