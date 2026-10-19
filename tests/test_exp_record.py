"""`labbrain exp record`: experiment notes from tracker runs."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from helpers import RUNS_FIXTURE, commit_all, copy_fixture, copy_runs, git

from labbrain.cli import main
from labbrain.experiments import append_to_section, run_status, split_of
from labbrain.notes import parse_note, update_frontmatter

PARENT = "EXP-20260910-label-smoothing"
HYPOTHESIS = "A lower learning rate with dropout beats label smoothing alone."


@pytest.fixture(autouse=True)
def _no_author_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_AUTHOR", raising=False)


@pytest.fixture
def runs_vault(vault_dir: Path) -> Path:
    copy_runs(vault_dir)
    return vault_dir


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def record(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    return run(capsys, "exp", "record", *argv)


def variant(
    vault: Path, run_id: str, *, base: str = "run-c1", drop: str = "", meta: str = ""
) -> None:
    """A copy of a fixture run, optionally without one config line prefix, or with new meta."""
    target = vault / "runs" / run_id
    shutil.copytree(RUNS_FIXTURE / base, target)
    if drop:
        cfg = target / "config.yaml"
        lines = cfg.read_text().splitlines(keepends=True)
        out, skipping = [], False
        for line in lines:
            if line.startswith(drop):
                skipping = True
                continue
            if skipping and line.startswith(" "):
                continue
            skipping = False
            out.append(line)
        cfg.write_text("".join(out))
    if meta:
        (target / "meta.json").write_text(meta)


def new_experiments(vault: Path) -> list[Path]:
    return sorted((vault / "experiments").glob("EXP-20261015-*.md"))


def test_record_done_from_child_runs(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = record(
        capsys,
        "run-c1",
        "run-c2",
        "--author",
        "claude",
        "--title",
        "Lower LR with dropout",
        "--parent",
        PARENT,
        "--hypothesis",
        HYPOTHESIS,
        "--summary",
        "Two folds of the lower-LR dropout variant.",
    )
    assert code == 0, err
    path = Path(out.strip())
    assert path.is_absolute() and path.name == "EXP-20261015-lower-lr-with-dropout.md"
    data = parse_note(path, runs_vault).data
    assert data is not None
    assert data["status"] == "done"
    assert data["protocol"] == "EVAL-v2" and data["dataset"] == "DS-20260801-main-split"
    assert data["tracker"] == {"backend": "local", "run_ids": ["run-c1", "run-c2"], "url": None}
    assert data["code"] == {"repo": None, "sha": "5d6e7f8", "dirty": False}
    assert data["config_hash"] is None
    assert data["links"] == [PARENT]
    assert data["hypothesis"] == HYPOTHESIS
    assert [(m["name"], m["split"], m["run_id"]) for m in data["metrics"]] == [
        ("epoch", None, "run-c1"),
        ("test.auroc", "test", "run-c1"),
        ("val.auroc", "val", "run-c1"),
        ("epoch", None, "run-c2"),
        ("test.auroc", "test", "run-c2"),
        ("val.auroc", "val", "run-c2"),
    ]
    assert all(m["as_of"] == date(2026, 10, 15) for m in data["metrics"])
    text = path.read_text()
    assert "&id" not in text  # one date object shared by many fields: no YAML anchors
    assert "## For future agents\n\nTwo folds of the lower-LR dropout variant.\n" in text
    assert f"## Hypothesis\n\n{HYPOTHESIS}\n" in text
    assert "| optim.lr | 0.001 | 0.0003 |" in text
    assert "Varied across these runs: data.fold." in text
    assert "| test.auroc | 0.85 | test | run-c1 |" in text
    assert run(capsys, "validate", str(path))[0] == 0


def test_without_parent_setup_lists_the_runs(
    runs_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = record(capsys, "run-c1", "run-c2", "--author", "claude", "--title", "Two folds")
    assert code == 0
    assert (
        "Runs: run-c1, run-c2.\nVaried across these runs: data.fold.\n"
        in Path(out.strip()).read_text()
    )


@pytest.mark.parametrize("flag", ["--parent", "--link"])
def test_unknown_parent_or_link_writes_nothing(
    runs_vault: Path, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    code, _, err = record(
        capsys, "run-c1", "--author", "claude", "--title", "X", flag, "EXP-20990101-nope"
    )
    assert code == 2 and "no note with ID" in err
    assert new_experiments(runs_vault) == []


def test_done_gate_missing_protocol(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = record(capsys, "run-noproto", "--author", "claude", "--title", "No protocol")
    assert code == 2
    assert err == (
        "labbrain: protocol required to record finished runs: "
        "pass --protocol or set eval.protocol in the run config\n"
    )
    assert new_experiments(runs_vault) == []


def test_done_gate_missing_dataset(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-nodata", drop="data:")
    code, _, err = record(capsys, "run-nodata", "--author", "claude", "--title", "No dataset")
    assert code == 2
    assert "dataset required to record finished runs: pass --dataset or set data.dataset" in err
    assert new_experiments(runs_vault) == []


def test_done_gate_missing_both(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-bare", base="run-noproto", drop="data:")
    code, _, err = record(capsys, "run-bare", "--author", "claude", "--title", "Bare")
    assert code == 2
    assert (
        "protocol and dataset required to record finished runs: pass --protocol/--dataset"
        " or set eval.protocol/data.dataset in the run config"
    ) in err


def test_explicit_protocol_satisfies_the_gate(
    runs_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = record(
        capsys, "run-noproto", "--author", "claude", "--title", "Given", "--protocol", "EVAL-v2"
    )
    assert code == 0
    assert parse_note(Path(out.strip()), runs_vault).data["protocol"] == "EVAL-v2"


def test_unknown_protocols_are_not_echoed(
    runs_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = record(
        capsys, "run-noproto", "--author", "claude", "--title", "X", "--protocol", "EVAL-v9"
    )
    assert code == 2 and err == "labbrain: protocol not found\n"
    variant(runs_vault, "run-v7", base="run-noproto")
    cfg = runs_vault / "runs" / "run-v7" / "config.yaml"
    cfg.write_text(cfg.read_text() + "eval:\n  protocol: EVAL-v7\n")
    code, _, err = record(capsys, "run-v7", "--author", "claude", "--title", "X")
    assert code == 2 and "EVAL-v7" not in err


def test_unknown_dataset(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = record(
        capsys, "run-c1", "--author", "claude", "--title", "X", "--dataset", "DS-20990101-nope"
    )
    assert code == 2 and err == "labbrain: dataset not found\n"


def test_runs_disagree_on_protocol(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-v1", base="run-noproto")
    cfg = runs_vault / "runs" / "run-v1" / "config.yaml"
    cfg.write_text(cfg.read_text() + "eval:\n  protocol: EVAL-v1\n")
    code, _, err = record(capsys, "run-c1", "run-v1", "--author", "claude", "--title", "Mixed")
    assert code == 2 and err == "labbrain: runs disagree on protocol; pass --protocol\n"
    code, _, _ = record(
        capsys,
        "run-c1",
        "run-v1",
        "--author",
        "claude",
        "--title",
        "Mixed",
        "--protocol",
        "EVAL-v2",
    )
    assert code == 0


def test_runs_disagree_on_dataset(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-d2")
    cfg = runs_vault / "runs" / "run-d2" / "config.yaml"
    cfg.write_text(cfg.read_text().replace("DS-20260801-main-split", "DS-20260802-other-split"))
    code, _, err = record(capsys, "run-c1", "run-d2", "--author", "claude", "--title", "Mixed data")
    assert code == 2 and err == "labbrain: runs disagree on dataset; pass --dataset\n"
    assert new_experiments(runs_vault) == []


@pytest.mark.parametrize(
    ("run_id", "status"), [("run-failed", "failed"), ("run-nometrics", "running")]
)
def test_failed_and_running_runs(
    runs_vault: Path, capsys: pytest.CaptureFixture[str], run_id: str, status: str
) -> None:
    code, out, _ = record(capsys, run_id, "--author", "claude", "--title", f"Status {status}")
    assert code == 0
    path = Path(out.strip())
    assert parse_note(path, runs_vault).data["status"] == status
    assert run(capsys, "validate", str(path))[0] == 0


def test_running_runs_need_no_protocol(
    runs_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    variant(runs_vault, "run-early", base="run-noproto")
    (runs_vault / "runs" / "run-early" / "metrics.json").unlink()
    code, out, _ = record(capsys, "run-early", "--author", "claude", "--title", "Early")
    assert code == 0
    data = parse_note(Path(out.strip()), runs_vault).data
    assert data["status"] == "running" and data["protocol"] is None


def test_disagreeing_shas_record_no_code(
    runs_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    variant(runs_vault, "run-other-sha", meta='{"git_sha": "abcdef1"}')
    (runs_vault / "runs" / "run-other-sha" / "metrics.json").write_text('{"m": 1}')
    code, out, _ = record(
        capsys, "run-c1", "run-other-sha", "--author", "claude", "--title", "Two shas"
    )
    assert code == 0 and parse_note(Path(out.strip()), runs_vault).data["code"] is None


def test_a_dirty_run_marks_code_dirty(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-dirty", meta='{"git_sha": "5d6e7f8", "git_dirty": true}')
    code, out, _ = record(capsys, "run-c1", "run-dirty", "--author", "claude", "--title", "Dirty")
    assert code == 0
    assert parse_note(Path(out.strip()), runs_vault).data["code"]["dirty"] is True


def test_code_falls_back_to_the_code_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code_repo = tmp_path / "code"
    shutil.copytree(RUNS_FIXTURE, code_repo / "runs")
    git(code_repo, "init", "-q", "-b", "main")
    commit_all(code_repo)
    vault = copy_fixture(tmp_path / "vault")
    cfg = vault / ".labbrain" / "config.yaml"
    cfg.write_text(cfg.read_text() + "code_repo: ../code\n")
    monkeypatch.setenv("LABBRAIN_NOW", "2026-10-15T12:00:00")
    monkeypatch.setenv("LABBRAIN_VAULT", str(vault))
    code, out, _ = record(
        capsys, "run-noproto", "--author", "claude", "--title", "From repo", "--protocol", "EVAL-v2"
    )
    assert code == 0
    sha = git(code_repo, "rev-parse", "HEAD").strip()
    assert parse_note(Path(out.strip()), vault).data["code"] == {
        "repo": "../code",
        "sha": sha,
        "dirty": False,
    }


def test_into_fills_a_planned_note(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, out, _ = run(
        capsys,
        "new",
        "experiment",
        "--title",
        "Planned lower LR",
        "--author",
        "claude",
        "--summary",
        "Planned.",
    )
    planned = Path(out.strip())
    planned.write_text(
        planned.read_text().replace(
            "## Setup\n", "## Setup\n\nPlanned: lower the learning rate and add dropout.\n"
        )
    )
    update_frontmatter(planned, {"hypothesis": "Lower LR helps."})
    code, out, err = record(
        capsys, "run-c1", "run-c2", "--author", "claude", "--into", planned.stem, "--parent", PARENT
    )
    assert code == 0, err
    assert Path(out.strip()).resolve() == planned.resolve()
    data = parse_note(planned, runs_vault).data
    assert data["status"] == "done" and data["title"] == "Planned lower LR"
    assert data["hypothesis"] == "Lower LR helps." and data["links"] == [PARENT]
    text = planned.read_text()
    assert "&id" not in text  # one date object shared by many fields: no YAML anchors
    setup = text.index("## Setup")
    assert (
        setup < text.index("Planned: lower the learning rate") < text.index("Config diff against")
    )
    assert (
        text.index("Config diff against") < text.index("## Results") < text.index("| test.auroc |")
    )
    assert run(capsys, "validate", str(planned))[0] == 0


def test_into_refuses_finished_notes(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    done = runs_vault / "experiments" / "EXP-20260901-baseline.md"
    before = done.read_bytes()
    code, _, err = record(capsys, "run-c1", "--author", "claude", "--into", "EXP-20260901-baseline")
    assert code == 2
    assert err == (
        "labbrain: EXP-20260901-baseline is done; only planned or running experiments can be filled in\n"
    )
    assert done.read_bytes() == before


def planned_note(capsys: pytest.CaptureFixture[str], title: str) -> Path:
    _, out, _ = run(capsys, "new", "experiment", "--title", title, "--author", "claude")
    return Path(out.strip())


def test_into_frontmatter_failure_writes_nothing(
    runs_vault: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import labbrain.experiments as experiments

    planned = planned_note(capsys, "Atomic fill")
    before = planned.read_bytes()
    real = experiments.update_frontmatter_text

    def broken(*args: object, **kwargs: object) -> str | None:
        raise ValueError("Atomic fill: frontmatter cannot be updated (line 3)")

    monkeypatch.setattr(experiments, "update_frontmatter_text", broken)
    code, _, err = record(capsys, "run-c1", "--author", "claude", "--into", planned.stem)
    assert code == 2
    assert err == f"labbrain: {planned.stem}: frontmatter cannot be updated\n"
    assert planned.read_bytes() == before
    monkeypatch.setattr(experiments, "update_frontmatter_text", real)
    code, _, err = record(capsys, "run-c1", "--author", "claude", "--into", planned.stem)
    assert code == 0, err
    text = planned.read_text()
    assert text.count("Runs: run-c1.") == 1 and text.count("| metric | value |") == 1
    assert parse_note(planned, runs_vault).data["status"] == "done"


def test_into_prefers_the_planned_protocol(
    runs_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planned = planned_note(capsys, "Planned on v1")
    update_frontmatter(planned, {"protocol": "EVAL-v1", "dataset": "DS-20260801-main-split"})
    code, _, err = record(capsys, "run-c1", "--author", "claude", "--into", planned.stem)
    assert code == 0, err
    data = parse_note(planned, runs_vault).data
    assert data["protocol"] == "EVAL-v1" and data["dataset"] == "DS-20260801-main-split"


def test_into_keeps_existing_links_first(
    runs_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planned = planned_note(capsys, "Linked plan")
    update_frontmatter(planned, {"links": ["EXP-20260901-baseline"]})
    code, _, err = record(
        capsys, "run-c1", "--author", "claude", "--into", planned.stem, "--parent", PARENT
    )
    assert code == 0, err
    assert parse_note(planned, runs_vault).data["links"] == ["EXP-20260901-baseline", PARENT]


def test_into_unknown_note(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = record(capsys, "run-c1", "--author", "claude", "--into", "EXP-20990101-nope")
    assert code == 2 and "no experiment with ID" in err


def test_title_and_into_are_exclusive(runs_vault: Path) -> None:
    for extra in (["--title", "X", "--into", PARENT], []):
        with pytest.raises(SystemExit) as info:
            main(["exp", "record", "run-c1", "--author", "claude", *extra])
        assert info.value.code == 2


def test_record_with_finish(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = record(
        capsys,
        "run-c1",
        "--author",
        "claude",
        "--title",
        "Finished in one call",
        "--finish",
        "exp-log: Finished in one call",
    )
    assert code == 0
    assert "[[EXP-20261015-finished-in-one-call]]" in (runs_vault / "index.md").read_text()
    assert "exp-log: Finished in one call" in (runs_vault / "log" / "2026-10-15.md").read_text()


@pytest.mark.parametrize(
    ("name", "split"),
    [
        ("test/auroc", "test"),
        ("val.loss", "val"),
        ("validation.f1", "validation"),
        ("valid.acc", "valid"),
        ("train.loss", "train"),
        ("auroc", None),
        ("test", None),
        ("testing.auroc", None),
    ],
)
def test_split_of(name: str, split: str | None) -> None:
    assert split_of(name) == split


def test_run_status() -> None:
    assert run_status(["finished", "failed", "running"]) == "failed"
    assert run_status(["finished", "unknown"]) == "running"
    assert run_status(["finished", "finished"]) == "done"


def test_append_to_section_respects_fences_and_line_endings() -> None:
    text = (
        "---\nid: x\n---\n## Hypothesis\n\n```\n## Setup\n```\n\n## Setup\n\nPlan.\n\n## Results\n"
    )
    out = append_to_section(text, "Setup", "Block.\n")
    assert out == (
        "---\nid: x\n---\n## Hypothesis\n\n```\n## Setup\n```\n\n"
        "## Setup\n\nPlan.\n\nBlock.\n\n## Results\n"
    )
    crlf = "---\r\nid: x\r\n---\r\n## Setup\r\n## Results\r\n"
    assert append_to_section(crlf, "Setup", "Block.\n") == (
        "---\r\nid: x\r\n---\r\n## Setup\r\n\r\nBlock.\r\n\r\n## Results\r\n"
    )
