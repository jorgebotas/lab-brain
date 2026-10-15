from __future__ import annotations

from pathlib import Path

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
