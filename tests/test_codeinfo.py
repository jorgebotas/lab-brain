"""`code_sha` and `labbrain code sha`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, commit_all, git, make_vault, write

from labbrain.cli import main
from labbrain.codeinfo import CodeError, code_sha


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)


def code_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    write(path, "train.py", "print('train')\n")
    commit_all(path)
    return path


def test_clean_repo(tmp_path: Path) -> None:
    repo = code_repo(tmp_path / "code")
    info = code_sha(repo)
    assert info.sha == git(repo, "rev-parse", "HEAD").strip() and len(info.sha) == 40
    assert info.dirty is False


def test_tracked_and_untracked_changes_are_dirty(tmp_path: Path) -> None:
    repo = code_repo(tmp_path / "code")
    write(repo, "train.py", "print('changed')\n")
    assert code_sha(repo).dirty is True
    git(repo, "checkout", "--", "train.py")
    write(repo, "new.py", "x = 1\n")
    assert code_sha(repo).dirty is True


def test_changes_inside_the_vault_are_ignored(tmp_path: Path) -> None:
    repo = code_repo(tmp_path / "code")
    vault = make_vault(repo / "brain")
    commit_all(repo)
    write(vault, "ideas/inbox/IDEA-20261015-x.md", "x\n")
    assert code_sha(repo, exclude=vault).dirty is False
    assert code_sha(repo).dirty is True


def test_not_a_repository(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    for path in (tmp_path / "plain", tmp_path / "missing"):
        with pytest.raises(CodeError, match="^not a git repository$"):
            code_sha(path)


def test_repository_without_commits(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    git(repo, "init", "-q")
    with pytest.raises(CodeError, match="no commits"):
        code_sha(repo)


def test_cli_uses_code_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = code_repo(tmp_path / "code")
    vault = make_vault(tmp_path / "v", MIN_CONFIG + "code_repo: ../code\n")
    assert main(["--vault", str(vault), "code", "sha"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"repo": "../code", "sha": code_sha(repo).sha, "dirty": False}


def test_cli_explicit_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = code_repo(tmp_path / "code")
    vault = make_vault(tmp_path / "v")
    assert main(["--vault", str(vault), "code", "sha", "--repo", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["repo"] == str(repo)


def test_cli_without_a_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = make_vault(tmp_path / "v")
    assert main(["--vault", str(vault), "code", "sha"]) == 2
    assert capsys.readouterr().err == "labbrain: code repo not set\n"
