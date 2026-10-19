"""`labbrain finish`: validate, then sync, index and log; and `new --finish`."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import note_text, write

from labbrain.cli import main

LOG = Path("log") / "2026-10-15.md"


@pytest.fixture(autouse=True)
def _no_author_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_AUTHOR", raising=False)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_finish_indexes_and_logs_a_clean_note(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out, _ = run(
        capsys,
        "new",
        "idea",
        "--title",
        "Cosine warmup",
        "--author",
        "claude",
        "--summary",
        "Warmup idea.",
    )
    code, out, _ = run(
        capsys, "finish", out.strip(), "--log", "idea: Cosine warmup", "--author", "claude"
    )
    assert code == 0 and "index.md updated" in out
    assert "[[IDEA-20261015-cosine-warmup]]" in (vault_dir / "index.md").read_text()
    assert "[claude] idea: Cosine warmup" in (vault_dir / LOG).read_text()


def test_finish_stops_on_validation_errors(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = write(
        vault_dir,
        "ideas/inbox/IDEA-20261015-broken.md",
        note_text("IDEA-20261015-broken", "idea", status="bogus"),
    )
    index_before = (vault_dir / "index.md").read_bytes()
    code, out, _ = run(capsys, "finish", str(bad), "--log", "idea: broken")
    assert code == 1 and "error" in out
    assert "index.md" not in out
    assert (vault_dir / "index.md").read_bytes() == index_before
    assert not (vault_dir / LOG).exists()


def test_finish_runs_sync(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    new = write(
        vault_dir,
        "decisions/ADR-20261015-switch-protocol.md",
        note_text(
            "ADR-20261015-switch-protocol",
            "decision",
            status="accepted",
            supersedes="ADR-20260905-adopt-eval-v2",
        ),
    )
    code, out, _ = run(capsys, "finish", str(new), "--log", "decide: switch protocol")
    assert code == 0 and "superseded" in out
    old = (vault_dir / "decisions" / "ADR-20260905-adopt-eval-v2.md").read_text()
    assert "superseded_by: ADR-20261015-switch-protocol" in old
    assert "[[ADR-20261015-switch-protocol]]" in (vault_dir / "index.md").read_text()


def test_new_with_finish_is_one_call(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(
        capsys,
        "new",
        "idea",
        "--title",
        "Cosine warmup",
        "--author",
        "claude",
        "--summary",
        "Warmup idea.",
        "--body",
        "Don't forget it.",
        "--finish",
        "idea: Cosine warmup",
    )
    assert code == 0
    first = Path(out.splitlines()[0])
    assert first.is_absolute() and first.name == "IDEA-20261015-cosine-warmup.md"
    assert "[[IDEA-20261015-cosine-warmup]]" in (vault_dir / "index.md").read_text()
    assert "[claude] idea: Cosine warmup" in (vault_dir / LOG).read_text()


def test_finish_refuses_paths_outside_the_vault(
    vault_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stray = tmp_path / "elsewhere.md"
    stray.write_text("x\n")
    code, _, err = run(capsys, "finish", str(stray), "--log", "x")
    assert code == 2 and "outside the vault" in err


def test_finish_refuses_empty_log_text(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    note = vault_dir / "ideas" / "inbox" / "IDEA-20261010-smoothing-schedule.md"
    code, _, err = run(capsys, "finish", str(note), "--log", "  ")
    assert code == 2 and "--log" in err


def test_finish_refuses_control_only_log_text_before_writing(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    note = vault_dir / "ideas" / "inbox" / "IDEA-20261010-smoothing-schedule.md"
    (vault_dir / "index.md").write_text("stale\n")
    code, _, err = run(capsys, "finish", str(note), "--log", "\x07\x1b\x7f")
    assert code == 2 and err == "labbrain: --log text is empty\n"
    assert (vault_dir / "index.md").read_text() == "stale\n"
    assert not (vault_dir / LOG).exists()


def test_new_with_empty_finish_text_is_refused(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run(
        capsys, "new", "idea", "--title", "Empty log", "--author", "claude", "--finish", ""
    )
    assert code == 2 and err == "labbrain: --log text is empty\n"
    assert Path(out.strip()).is_file()
    assert "IDEA-20261015-empty-log" not in (vault_dir / "index.md").read_text()


def test_sync_command_output_is_unchanged(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "sync", "--dry-run")
    assert code == 0 and out == "0 error(s), 0 warning(s), 0 info\n"
