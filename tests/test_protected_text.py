"""Protected projects: `new` and `exp record` refuse note text that matches a PHI pattern."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from helpers import copy_runs

from labbrain.cli import main
from labbrain.notes import parse_note, update_frontmatter
from labbrain.phi import line_hash

RNG = random.Random(4242)
MRN = "".join(str(RNG.randrange(1, 10)) for _ in range(8))
EMAIL = "j" + "doe" + "@" + "example" + ".org"


@pytest.fixture(autouse=True)
def _no_author_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_AUTHOR", raising=False)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def refused(rule: str) -> str:
    return f"labbrain: the note text matches a protected-data pattern ({rule}); rephrase it\n"


def created(vault: Path) -> list[Path]:
    return sorted(vault.rglob("*20261015*.md"))


@pytest.mark.parametrize(
    ("flag", "value", "rule"),
    [
        ("--title", f"Chart {MRN} review", "phi-mrn"),
        ("--summary", f"Ask {EMAIL} first.", "phi-email"),
        ("--body", f"Context.\nMRN {MRN} was seen.", "phi-mrn"),
    ],
    ids=["title", "summary", "body"],
)
def test_new_refuses_protected_text(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], flag: str, value: str, rule: str
) -> None:
    argv = ["new", "idea", "--author", "claude"]
    if flag != "--title":
        argv += ["--title", "Plain idea"]
    code, out, err = run(capsys, *argv, flag, value)
    assert code == 2 and out == "" and err == refused(rule)
    assert MRN not in err and EMAIL not in err
    assert created(vault_dir) == []


def test_new_reports_every_rule_once(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(
        capsys,
        "new",
        "idea",
        "--author",
        "claude",
        "--title",
        f"Chart {MRN}",
        "--body",
        f"{EMAIL}\nMRN {MRN}",
    )
    assert code == 2 and err == refused("phi-email, phi-mrn")


def test_allowlisted_lines_are_accepted(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    line = f"Chart {MRN} is a synthetic example."
    (vault_dir / ".labbrain" / "phi-allow.yaml").write_text(
        f"- file: ideas/inbox/IDEA-20261015-plain-idea.md\n  rule: phi-mrn\n"
        f"  line_sha256: {line_hash(line)}\n  author: alice\n  date: 2026-10-15\n"
    )
    code, out, err = run(
        capsys, "new", "idea", "--author", "alice", "--title", "Plain idea", "--body", line
    )
    assert code == 0, err
    assert line in Path(out.strip()).read_text()


def test_unprotected_projects_are_not_scanned(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = vault_dir / ".labbrain" / "config.yaml"
    config.write_text(config.read_text().replace("protected_data: true", "protected_data: false"))
    code, out, err = run(
        capsys, "new", "idea", "--author", "alice", "--title", "Plain idea", "--body", EMAIL
    )
    assert code == 0, err


@pytest.fixture
def runs_vault(vault_dir: Path) -> Path:
    copy_runs(vault_dir)
    return vault_dir


@pytest.mark.parametrize(
    ("flag", "value", "rule"),
    [
        ("--title", f"Chart {MRN} rerun", "phi-mrn"),
        ("--hypothesis", f"Patients like {EMAIL} respond.", "phi-email"),
    ],
    ids=["title", "hypothesis"],
)
def test_exp_record_refuses_protected_text(
    runs_vault: Path, capsys: pytest.CaptureFixture[str], flag: str, value: str, rule: str
) -> None:
    argv = ["exp", "record", "run-c1", "--author", "claude"]
    if flag != "--title":
        argv += ["--title", "Plain rerun"]
    code, out, err = run(capsys, *argv, flag, value)
    assert code == 2 and out == "" and err == refused(rule)
    assert created(runs_vault) == []


def test_into_refuses_new_protected_text_but_not_old(
    runs_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out, _ = run(capsys, "new", "experiment", "--title", "Plan", "--author", "alice")
    planned = Path(out.strip())
    before = planned.read_bytes()
    code, _, err = run(
        capsys,
        "exp",
        "record",
        "run-c1",
        "--author",
        "alice",
        "--into",
        planned.stem,
        "--hypothesis",
        f"MRN {MRN} responds.",
    )
    assert code == 2 and err == refused("phi-mrn")
    assert planned.read_bytes() == before
    # A finding already in the note is lint's to report; it does not block a fill.
    update_frontmatter(planned, {"hypothesis": f"Ask {EMAIL}."})
    code, _, err = run(
        capsys, "exp", "record", "run-c1", "--author", "alice", "--into", planned.stem
    )
    assert code == 0, err
    assert parse_note(planned, runs_vault).data["status"] == "done"
