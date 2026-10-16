from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from fixtures.mutations import BASELINE, EVAL_V2, IDEA_OPEN, RAW_PAPER, SMOOTHING, replace
from helpers import FIXTURE, TODAY, commit_all, git

from labbrain import gitutil, lint
from labbrain.gitutil import GitError
from labbrain.sync import apply, plan
from labbrain.vault import Vault


def frozen(root: Path, base: str | None = None) -> list[tuple[str, str, str]]:
    findings = lint.run(Vault.load(root), today=TODAY, base=base, only=["frozen-edit"])
    return [(f.severity, f.path, f.message) for f in findings]


def test_inserting_a_section_is_allowed(vault_dir: Path) -> None:
    with (vault_dir / BASELINE).open("a") as handle:
        handle.write("\n## Postmortem\n\nNothing to add.\n")
    assert frozen(vault_dir) == []


def test_idea_move_with_allowed_transition_is_clean(vault_dir: Path) -> None:
    src = vault_dir / IDEA_OPEN
    dest = vault_dir / "ideas" / "archive" / src.name
    text = src.read_text().replace(
        "status: open", "status: consolidated\nconsolidated_into: label-smoothing-calibration"
    )
    dest.write_text(text)
    src.unlink()
    (vault_dir / "index.md").unlink()
    findings = lint.run(Vault.load(vault_dir), today=TODAY)
    assert findings == [], [f.to_dict() for f in findings]


def test_sync_output_never_trips_frozen_edit(vault_dir: Path) -> None:
    replace(
        vault_dir,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )
    commit_all(vault_dir, "supersede baseline")
    vault = Vault.load(vault_dir)
    apply(vault, plan(vault)[0], TODAY)
    findings = lint.run(Vault.load(vault_dir), today=TODAY, only=["frozen-edit", "sync-pending"])
    assert findings == []


def test_sync_keeps_untouched_yaml11_scalars_verbatim(vault_dir: Path) -> None:
    """Loaded values ruamel reads as strings but PyYAML does not (yes, no, 12:30) are
    written back exactly as they were, so sync is still a frozen-edit-clean, few-line diff."""
    replace(vault_dir, BASELINE, "dirty: false}", "dirty: yes}\nstarted: 12:30\nreviewed: no")
    replace(
        vault_dir,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )
    commit_all(vault_dir, "supersede baseline")
    before = (vault_dir / BASELINE).read_text()
    assert [f.rule for f in lint.run(Vault.load(vault_dir), today=TODAY, only=["dirty-code"])] == [
        "dirty-code"
    ]
    vault = Vault.load(vault_dir)
    assert apply(vault, plan(vault)[0], TODAY) == ([BASELINE], [])
    after = (vault_dir / BASELINE).read_text()
    for line in ("dirty: yes}\n", "started: 12:30\n", "reviewed: no\n"):
        assert line in after
    removed = set(before.splitlines()) - set(after.splitlines())
    assert removed == {"updated: 2026-09-02", "status: done"}
    findings = lint.run(
        Vault.load(vault_dir), today=TODAY, only=["frozen-edit", "sync-pending", "dirty-code"]
    )
    assert [(f.rule, f.path) for f in findings] == [("dirty-code", BASELINE)]


def test_draft_protocol_referenced_by_done_experiment_is_frozen(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "status: frozen", "status: draft")
    commit_all(vault_dir, "draft protocol")
    replace(vault_dir, EVAL_V2, "ECE depends on the bin count.", "ECE is robust.")
    assert [m for _, _, m in frozen(vault_dir)] == [
        "existing body lines were modified or deleted; only insertions are allowed"
    ]


def test_draft_to_frozen_transition_is_allowed(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "status: frozen", "status: draft")
    commit_all(vault_dir, "draft protocol")
    replace(vault_dir, EVAL_V2, "status: draft", "status: frozen")
    assert frozen(vault_dir) == []


def test_base_option_catches_committed_violations(vault_dir: Path) -> None:
    replace(vault_dir, BASELINE, "Try label smoothing.", "Try something else.")
    commit_all(vault_dir, "sneaky rewrite")
    assert frozen(vault_dir) == []
    assert [p for _, p, _ in frozen(vault_dir, base="HEAD~1")] == [BASELINE]


def test_default_base_is_skipped_outside_git_and_in_an_empty_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    shutil.copytree(FIXTURE, plain)
    assert frozen(plain) == [("info", "", "not a git repository; frozen-edit skipped")]
    git(plain, "init", "-q", "-b", "main")
    assert frozen(plain) == [("info", "", "base revision HEAD not found; frozen-edit skipped")]


def test_explicit_base_that_cannot_be_resolved_is_an_error(tmp_path: Path, vault_dir: Path) -> None:
    """A base the caller named must be honoured: failing to resolve it fails closed."""
    assert frozen(vault_dir, base="no-such-ref") == [
        ("error", "", "base revision no-such-ref not found; frozen-edit could not run")
    ]
    plain = tmp_path / "plain"
    shutil.copytree(FIXTURE, plain)
    assert frozen(plain, base="HEAD") == [
        ("error", "", "not a git repository, so --base cannot be used; frozen-edit could not run")
    ]


def test_git_failure_while_resolving_the_base_is_an_error(
    vault_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(repo: gitutil.Repo, ref: str) -> str | None:
        raise GitError("git rev-parse failed")

    monkeypatch.setattr(gitutil, "resolve_ref", broken)
    assert frozen(vault_dir) == [
        ("error", "", "git failed while checking frozen notes; frozen-edit could not run")
    ]


def test_subfolder_vault_ignores_code_changes(tmp_path: Path) -> None:
    repo = tmp_path / "code"
    repo.mkdir()
    (repo / "train.py").write_text("x = 1\n")
    shutil.copytree(FIXTURE, repo / "brain")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo)
    (repo / "train.py").write_text("x = 2\n")
    brain = repo / "brain"
    assert frozen(brain) == []
    replace(brain, BASELINE, "status: done", "status: running")
    assert frozen(brain) == [
        ("error", BASELINE, "status change done → running is not allowed on a frozen experiment")
    ]


def test_messages_never_echo_invalid_status_or_unknown_keys(vault_dir: Path) -> None:
    replace(vault_dir, BASELINE, "status: done", "status: Jane Roe 555\nRoe-notes: x")
    assert frozen(vault_dir) == [
        ("error", BASELINE, "frozen field <unknown field> changed"),
        (
            "error",
            BASELINE,
            "status change done → <invalid status> is not allowed on a frozen experiment",
        ),
    ]


@pytest.mark.parametrize("failing", ["changed_files", "ls_tree", "read_blobs"])
def test_git_failure_mid_rule_is_an_error_not_a_crash(
    vault_dir: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    replace(vault_dir, BASELINE, "Try label smoothing.", "Try something else.")

    def fail(*args: object, **kwargs: object) -> None:
        raise GitError("git cat-file failed")

    monkeypatch.setattr(gitutil, failing, fail)
    assert frozen(vault_dir) == [
        ("error", "", "git failed while checking frozen notes; frozen-edit could not run")
    ]


def test_mis_cased_subfolder_vault_still_reports_violations(tmp_path: Path) -> None:
    repo = tmp_path / "code"
    repo.mkdir()
    shutil.copytree(FIXTURE, repo / "brain")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo)
    mis_cased = repo / "BRAIN"
    if not mis_cased.exists():
        pytest.skip("case-sensitive filesystem")
    replace(repo / "brain", BASELINE, "status: done", "status: running")
    assert frozen(mis_cased) == [
        ("error", BASELINE, "status change done → running is not allowed on a frozen experiment")
    ]


def test_adding_a_raw_file_is_allowed(vault_dir: Path) -> None:
    (vault_dir / "raw" / "papers" / "new-source.txt").write_text("A new source.\n")
    git(vault_dir, "add", "-A")
    assert frozen(vault_dir) == []
    commit_all(vault_dir, "ingest source")
    assert frozen(vault_dir, base="HEAD~1") == []


def test_raw_mode_only_change_is_allowed(vault_dir: Path) -> None:
    git(vault_dir, "config", "core.fileMode", "true")
    (vault_dir / RAW_PAPER).chmod(0o755)
    assert git(vault_dir, "diff", "--name-status", "HEAD").split() == ["M", RAW_PAPER]
    assert frozen(vault_dir) == []


@pytest.mark.parametrize(
    ("edit", "verb"),
    [
        (lambda path: path.write_bytes(path.read_bytes() + b"An added line.\n"), "modified"),
        (lambda path: path.unlink(), "deleted"),
    ],
    ids=["modified", "deleted"],
)
def test_existing_raw_file_changes_are_errors(
    vault_dir: Path, edit: Callable[[Path], None], verb: str
) -> None:
    edit(vault_dir / RAW_PAPER)
    assert frozen(vault_dir) == [
        ("error", RAW_PAPER, f"raw/ files are immutable; this file was {verb}")
    ]
