"""`labbrain new` flags for skills, and exclusive note creation."""

from __future__ import annotations

from pathlib import Path

import pytest

from labbrain import scaffold
from labbrain.cli import main
from labbrain.notes import atomic_create


@pytest.fixture(autouse=True)
def _no_author_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_AUTHOR", raising=False)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def new(capsys: pytest.CaptureFixture[str], *argv: str) -> Path:
    code, out, err = run(capsys, "new", *argv)
    assert code == 0, err
    return Path(out.strip())


def test_summary_replaces_the_placeholder_on_one_line(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = new(
        capsys,
        "idea",
        "--title",
        "Cosine warmup",
        "--author",
        "claude",
        "--summary",
        "Try warmup.\nOn the small model.",
    )
    text = path.read_text(encoding="utf-8")
    assert "## For future agents\n\nTry warmup. On the small model.\n" in text
    assert scaffold.FUTURE_AGENTS_PLACEHOLDER not in text
    assert run(capsys, "validate", str(path))[0] == 0


def test_summary_is_ignored_for_human_authors(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run(
        capsys,
        "new",
        "idea",
        "--title",
        "Cosine warmup",
        "--author",
        "alice",
        "--summary",
        "Try warmup.",
    )
    assert code == 0 and "--summary is ignored for human authors" in err
    assert "Try warmup." not in Path(out.strip()).read_text(encoding="utf-8")


def test_body_goes_after_the_future_agents_block(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = new(
        capsys,
        "idea",
        "--title",
        "Cosine warmup",
        "--author",
        "claude",
        "--summary",
        "Warmup idea.",
        "--body",
        "Don't forget cosine warmup.",
    )
    text = path.read_text(encoding="utf-8")
    assert text.index("## For future agents") < text.index("Don't forget cosine warmup.\n")
    assert run(capsys, "validate", str(path))[0] == 0


def test_body_goes_before_required_sections(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = new(
        capsys,
        "decision",
        "--title",
        "Pick a tracker",
        "--author",
        "alice",
        "--body",
        "Background note.",
    )
    text = path.read_text(encoding="utf-8")
    assert text.index("Background note.") < text.index("## Context")
    assert run(capsys, "validate", str(path))[0] == 0


def test_body_rejects_level_two_headings(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = run(
        capsys,
        "new",
        "idea",
        "--title",
        "Sneaky",
        "--author",
        "claude",
        "--body",
        "text\n## Sneaky heading",
    )
    assert code == 2 and "level-2 headings" in err
    assert not list((vault_dir / "ideas" / "inbox").glob("IDEA-20261015-*"))


def test_tags_are_deduplicated_in_order(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = new(
        capsys,
        "idea",
        "--title",
        "Cosine warmup",
        "--author",
        "alice",
        "--tag",
        "warmup",
        "--tag",
        "optim",
        "--tag",
        "warmup",
        "--tag",
        " ",
    )
    assert "tags: [warmup, optim]\n" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("note_type", "status"),
    [
        ("experiment", "running"),
        ("experiment", "planned"),
        ("decision", "accepted"),
        ("decision", "proposed"),
        ("idea", "open"),
    ],
)
def test_allowed_statuses_produce_valid_notes(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], note_type: str, status: str
) -> None:
    path = new(
        capsys, note_type, "--title", "Status check", "--author", "alice", "--status", status
    )
    assert f"status: {status}\n" in path.read_text(encoding="utf-8")
    assert run(capsys, "validate", str(path))[0] == 0


@pytest.mark.parametrize(
    ("note_type", "status"),
    [
        ("experiment", "done"),
        ("idea", "consolidated"),
        ("decision", "superseded"),
        ("protocol", "frozen"),
        ("experiment", "bogus48151623"),
    ],
)
def test_other_statuses_are_refused_without_echo(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], note_type: str, status: str
) -> None:
    code, _, err = run(
        capsys, "new", note_type, "--title", "Status check", "--author", "alice", "--status", status
    )
    assert code == 2 and "--status" in err
    assert "48151623" not in err


def test_atomic_create_never_replaces_a_file(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        atomic_create(target, "new text")
    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["note.md"]


def test_atomic_create_writes_a_new_file(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "note.md"
    atomic_create(target, "line\r\n")
    assert target.read_bytes() == b"line\r\n"


def test_create_retries_when_another_writer_wins(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = scaffold.atomic_create
    calls: list[Path] = []

    def racing(path: Path, text: str) -> None:
        calls.append(path)
        if len(calls) == 1:
            path.write_text("someone else's note\n", encoding="utf-8")
            raise FileExistsError(path)
        real(path, text)

    monkeypatch.setattr(scaffold, "atomic_create", racing)
    path = new(capsys, "handoff", "--title", "Wrap up", "--author", "claude")
    first, second = calls
    assert first.read_text(encoding="utf-8") == "someone else's note\n"
    assert path == second and second != first


def test_create_gives_up_after_five_attempts(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[Path] = []

    def always_taken(path: Path, text: str) -> None:
        attempts.append(path)
        raise FileExistsError(path)

    monkeypatch.setattr(scaffold, "atomic_create", always_taken)
    code, _, err = run(capsys, "new", "idea", "--title", "Crowded", "--author", "alice")
    assert code == 2 and "could not create" in err
    assert len(attempts) == scaffold.CREATE_ATTEMPTS
