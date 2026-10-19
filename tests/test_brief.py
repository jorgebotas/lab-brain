"""`labbrain brief`: a compact orientation for the start of a session."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, make_vault, note_text, write

from labbrain import __version__
from labbrain.cli import main


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_short_brief_on_the_fixture(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "brief", "--short")
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        f"Toy Image Classifier · engine {__version__}",
        "Last handoff: HO-20261014-1420-claude  Registered the headline AUROC claim",
        "Running 0 · Planned 0 · Stale claims 0 · Open ideas 1 · Lint errors 0",
    ]


def test_full_brief_on_the_fixture(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "brief")
    assert code == 0
    assert out.splitlines() == [
        f"Toy Image Classifier · engine {__version__}",
        "",
        "Recent handoffs:",
        "  HO-20261014-1420-claude  Registered the headline AUROC claim",
        "",
        "Experiments running (0):",
        "  none",
        "Experiments planned (0):",
        "  none",
        "Stale claims (0):",
        "  none",
        "",
        "Open ideas: 1 · Lint: 0 errors, 0 warnings",
    ]


@pytest.fixture
def busy_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LABBRAIN_NOW", "2026-10-15T12:00:00")
    root = make_vault(tmp_path / "v", MIN_CONFIG + "engine_min_version: 99.0.0\n")
    for day in range(1, 6):
        hid = f"HO-202610{day:02d}-0900-claude"
        write(root, f"handoffs/{hid}.md", note_text(hid, "handoff", title=f"Session {day}"))
    for i in range(7):
        eid = f"EXP-2026100{i}-run{i}"
        title = "Bad\x1btitle" if i == 6 else f"Running {i}"
        write(
            root,
            f"experiments/{eid}.md",
            note_text(eid, "experiment", status="running", title=title),
        )
    for i in range(2):
        eid = f"EXP-2026090{i}-plan{i}"
        write(root, f"experiments/{eid}.md", note_text(eid, "experiment", title=f"Plan {i}"))
    for i in range(6):
        cid = f"CLM-2026100{i}-claim{i}"
        write(root, f"claims/{cid}.md", note_text(cid, "claim", status="stale"))
    for i in range(3):
        iid = f"IDEA-2026100{i}-idea{i}"
        write(root, f"ideas/inbox/{iid}.md", note_text(iid, "idea"))
    write(
        root,
        "ideas/inbox/IDEA-20261009-broken.md",
        note_text("IDEA-20261009-broken", "idea", status="bogus"),
    )
    return root


def test_full_brief_stays_within_limits(
    busy_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run(capsys, "--vault", str(busy_vault), "brief")
    lines = out.splitlines()
    assert code == 0 and err == "" and len(lines) <= 40
    assert sum("99.0.0" in line for line in lines) == 1
    assert lines[4:7] == [
        "  HO-20261005-0900-claude  Session 5",
        "  HO-20261004-0900-claude  Session 4",
        "  HO-20261003-0900-claude  Session 3",
    ]
    assert "Experiments running (7):" in lines
    assert "  EXP-20261006-run6  Bad title" in lines
    assert "  … and 2 more" in lines and "  … and 1 more" in lines
    assert "Experiments planned (2):" in lines and "Stale claims (6):" in lines
    assert re.fullmatch(r"Open ideas: 3 · Lint: [1-9]\d* errors, \d+ warnings", lines[-1])


def test_short_brief_stays_within_limits(
    busy_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run(capsys, "--vault", str(busy_vault), "brief", "--short")
    lines = out.splitlines()
    assert code == 0 and err == "" and len(lines) == 4
    assert lines[2] == "Last handoff: HO-20261005-0900-claude  Session 5"
    assert lines[3].startswith(
        "Running 7 · Planned 2 · Stale claims 6 · Open ideas 3 · Lint errors "
    )


def test_brief_without_handoffs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_vault(tmp_path / "v")
    code, out, _ = run(capsys, "--vault", str(root), "brief", "--short")
    assert code == 0 and "Last handoff: none" in out.splitlines()


def test_brief_strips_controls_from_note_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_vault(tmp_path / "v")
    bad = "\x1b[31m"
    bidi = "\u202e"
    eid = f"EXP-20261001-a{bad}red{bidi}"
    write(root, f"experiments/{eid}.md", note_text(eid, "experiment", status="running"))
    hid = f"HO-20261009-0900-a{bad}red{bidi}"
    write(root, f"handoffs/{hid}.md", note_text(hid, "handoff", title="Session"))
    for argv in (("brief",), ("brief", "--short")):
        code, out, _ = run(capsys, "--vault", str(root), *argv)
        assert code == 0
        assert "\x1b" not in out and bidi not in out
        assert "red" in out


def _section(lines: list[str], header: str) -> list[str]:
    start = lines.index(header) + 1
    end = next(i for i in range(start, len(lines)) if not lines[i].startswith("  "))
    return lines[start:end]


def test_full_brief_listing_rows_and_exact_counts(
    busy_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from labbrain import lint
    from labbrain.vault import Vault, load_config

    findings = lint.run(Vault.load(busy_vault, load_config(busy_vault)))
    errors = sum(f.severity == "error" for f in findings)
    warnings = sum(f.severity == "warning" for f in findings)
    assert errors and warnings
    code, out, _ = run(capsys, "--vault", str(busy_vault), "brief")
    lines = out.splitlines()
    assert code == 0
    running = _section(lines, "Experiments running (7):")
    assert len(running) == 6 and running[-1] == "  … and 2 more"
    assert running[0] == "  EXP-20261006-run6  Bad title"
    planned = _section(lines, "Experiments planned (2):")
    assert planned == ["  EXP-20260901-plan1  Plan 1", "  EXP-20260900-plan0  Plan 0"]
    stale = _section(lines, "Stale claims (6):")
    assert len(stale) == 6 and stale[-1] == "  … and 1 more"
    assert lines[-1] == f"Open ideas: 3 · Lint: {errors} errors, {warnings} warnings"
    code, out, _ = run(capsys, "--vault", str(busy_vault), "brief", "--short")
    assert out.splitlines()[3].endswith(f"Lint errors {errors}")


def test_brief_strips_controls_from_the_project_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = MIN_CONFIG.replace("project_name: Toy", 'project_name: "Toy\\e[31m\\u202eLab\\n"')
    root = make_vault(tmp_path / "v", config)
    for argv in (("brief",), ("brief", "--short")):
        code, out, _ = run(capsys, "--vault", str(root), *argv)
        assert code == 0
        assert out.splitlines()[0] == f"Toy [31m Lab · engine {__version__}"
