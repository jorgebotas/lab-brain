"""The local tracker adapter, `describe`, and `labbrain tracker fetch`."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, copy_runs, make_vault, write

from labbrain.cli import main
from labbrain.confighash import config_hash
from labbrain.trackers import describe, get_adapter, headline
from labbrain.trackers.base import TrackerError
from labbrain.trackers.local import LocalAdapter
from labbrain.vault import load_config


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = make_vault(tmp_path / "v")
    copy_runs(root)
    return root


def adapter(root: Path) -> LocalAdapter:
    found = get_adapter(load_config(root), root)
    assert isinstance(found, LocalAdapter)
    return found


def add_run(root: Path, run_id: str, files: dict[str, str]) -> None:
    for name, text in files.items():
        write(root, f"runs/{run_id}/{name}", text)


def test_fetch_reads_config_metrics_and_meta(vault: Path) -> None:
    [rec] = adapter(vault).fetch(["run-c1"])
    assert rec["run_id"] == "run-c1" and rec["name"] == "lr-dropout-fold0"
    assert rec["config"]["optim.lr"] == 0.0003
    assert rec["config"]["eval.protocol"] == "EVAL-v2"
    assert rec["summary"] == {"test.auroc": 0.85, "val.auroc": 0.86, "epoch": 20.0}
    assert rec["status"] == "finished"
    assert rec["git_sha"] == "5d6e7f8"
    assert rec["git_dirty"] is False
    assert rec["tags"] == ["lr-sweep"]
    assert rec["started_at"] == datetime(2026, 10, 12, 9, 0)
    assert rec["ended_at"] == datetime(2026, 10, 12, 11, 0)
    assert rec["notes"] is not None and rec["notes"].startswith("Hypothesis:")
    assert rec["url"] is None


def test_fetch_keeps_request_order(vault: Path) -> None:
    assert [r["run_id"] for r in adapter(vault).fetch(["run-c2", "run-c1"])] == ["run-c2", "run-c1"]


def test_metrics_keep_only_finite_numbers(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    add_run(
        root,
        "r1",
        {
            "config.yaml": "a: 1\n",
            "metrics.json": '{"ok": 1, "flag": true, "name": "x", "bad": NaN, "nested": {"f": 0.5}}',
        },
    )
    assert adapter(root).fetch(["r1"])[0]["summary"] == {"ok": 1.0, "nested.f": 0.5}


@pytest.mark.parametrize(
    ("run_id", "status"),
    [("run-failed", "failed"), ("run-nometrics", "unknown"), ("run-noproto", "finished")],
)
def test_status_precedence(vault: Path, run_id: str, status: str) -> None:
    assert adapter(vault).fetch([run_id])[0]["status"] == status


def test_badly_typed_meta_values_are_ignored(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    add_run(
        root,
        "r1",
        {
            "config.yaml": "a: 1\n",
            "metrics.json": '{"m": 1}',
            "meta.json": '{"status": "exploded", "git_sha": "not-a-sha", "tags": "x",'
            ' "git_dirty": "yes", "started_at": "yesterday", "name": 7}',
        },
    )
    rec = adapter(root).fetch(["r1"])[0]
    assert rec["status"] == "finished"
    assert rec["git_sha"] is None and rec["git_dirty"] is None
    assert rec["tags"] == [] and rec["started_at"] is None and rec["name"] is None


@pytest.mark.parametrize("bad", ["../escape", ".hidden", "a/b", "", "run 1", "-flag"])
def test_invalid_run_ids_are_refused_without_echo(vault: Path, bad: str) -> None:
    with pytest.raises(TrackerError) as info:
        adapter(vault).fetch([bad])
    assert str(info.value) == "invalid run id"


def test_missing_run_names_the_file(vault: Path) -> None:
    with pytest.raises(TrackerError, match=r"^run run-missing: config.yaml not found$"):
        adapter(vault).fetch(["run-missing"])


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"config.yaml": "a: [oops48151623\n"}, "config.yaml is not valid YAML"),
        ({"config.yaml": "- 48151623\n"}, "config.yaml is not a mapping"),
        ({"config.yaml": "a: 1\n", "metrics.json": "{48151623"}, "metrics.json is not valid JSON"),
        ({"config.yaml": "a: 1\n", "meta.json": "[48151623]"}, "meta.json is not valid JSON"),
        ({"config.yaml": "when: 2026-13-45\n"}, "config.yaml is not valid YAML"),
        ({"config.yaml": "a: &x {b: *x}\n"}, "config.yaml is not valid YAML"),
        ({"config.yaml": "a: " + "[" * 5000 + "]" * 5000}, "config.yaml is not valid YAML"),
        ({"config.yaml": 'a: "x\\udc85"\n'}, "config.yaml is not valid YAML"),
        (
            {"config.yaml": "a: 1\n", "metrics.json": '{"m":' + "[" * 100000 + "]" * 100000 + "}"},
            "metrics.json is not valid JSON",
        ),
        (
            {"config.yaml": "a: 1\n", "metrics.json": '{"m\\udc85": 1}'},
            "metrics.json is not valid JSON",
        ),
        (
            {"config.yaml": "a: 1\n", "meta.json": '{"url": "x\\udc85"}'},
            "meta.json is not valid JSON",
        ),
        (
            {"config.yaml": "a.b: 48151623\na:\n  b: 2\n"},
            "config.yaml has keys that collide when flattened",
        ),
        (
            {"config.yaml": "a: 1\n", "metrics.json": '{"m.n": 48151623, "m": {"n": 2}}'},
            "metrics.json has keys that collide when flattened",
        ),
    ],
)
def test_unreadable_files_are_reported_without_content(
    tmp_path: Path, files: dict[str, str], message: str
) -> None:
    root = make_vault(tmp_path / "v")
    add_run(root, "r1", files)
    with pytest.raises(TrackerError) as info:
        adapter(root).fetch(["r1"])
    assert str(info.value) == f"run r1: {message}"
    assert "48151623" not in str(info.value)


def test_runs_dir_resolution(tmp_path: Path) -> None:
    plain = make_vault(tmp_path / "v")
    assert adapter(plain).runs_dir == (plain / "runs").resolve()
    (tmp_path / "code").mkdir()
    beside = make_vault(tmp_path / "w", MIN_CONFIG + "code_repo: ../code\n")
    assert adapter(beside).runs_dir == (tmp_path / "code" / "runs").resolve()
    absolute = make_vault(
        tmp_path / "x", MIN_CONFIG + f"tracker: {{runs_dir: '{tmp_path / 'abs'}'}}\n"
    )
    assert adapter(absolute).runs_dir == (tmp_path / "abs").resolve()


def test_runs_dir_inside_a_data_path_is_refused(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v", MIN_CONFIG + "data_paths: [runs]\n")
    copy_runs(root)
    with pytest.raises(TrackerError, match="protected data path"):
        adapter(root).fetch(["run-c1"])


def test_one_run_inside_a_data_path_is_refused(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v", MIN_CONFIG + "data_paths: [runs/run-c1]\n")
    copy_runs(root)
    with pytest.raises(TrackerError, match="protected data path"):
        adapter(root).fetch(["run-c1"])
    assert adapter(root).fetch(["run-c2"])[0]["run_id"] == "run-c2"


def test_symlinked_run_into_a_data_path_is_refused(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    root = make_vault(tmp_path / "v", MIN_CONFIG + f"data_paths: ['{secret}']\n")
    copy_runs(root)
    shutil.copytree(root / "runs" / "run-c1", secret / "run-x")
    (root / "runs" / "run-x").symlink_to(secret / "run-x")
    with pytest.raises(TrackerError, match="protected data path"):
        adapter(root).fetch(["run-x"])


def test_run_url(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    add_run(root, "r1", {"config.yaml": "a: 1\n", "meta.json": '{"url": "https://example.org/r1"}'})
    add_run(root, "r2", {"config.yaml": "a: 1\n"})
    assert adapter(root).run_url("r1") == "https://example.org/r1"
    assert adapter(root).run_url("r2") is None


@pytest.mark.parametrize(
    ("backend", "message"),
    [
        ("wandb", "tracker backend 'wandb' arrives in a later engine version"),
        ("mlflow", "tracker backend 'mlflow' arrives in a later engine version"),
        ("none", "tracker backend 'none' is not supported by exp record yet"),
        ("comet48151623", "unknown tracker backend"),
    ],
)
def test_get_adapter_backends(tmp_path: Path, backend: str, message: str) -> None:
    root = make_vault(tmp_path / "v", MIN_CONFIG + f"tracker: {{backend: {backend}}}\n")
    with pytest.raises(TrackerError) as info:
        get_adapter(load_config(root), root)
    assert str(info.value) == message


def test_describe_adds_derived_keys(vault: Path) -> None:
    config = load_config(vault)
    [rec] = adapter(vault).fetch(["run-c1"])
    out = describe(rec, config)
    assert out["config_hash"] == config_hash(rec["config"], config.hash_ignore)
    assert out["config_hash"].startswith("sha256:")
    assert out["protocol"] == "EVAL-v2"
    assert out["dataset"] == "DS-20260801-main-split"
    assert out["headline"] == rec["summary"]
    assert out["started_at"] == "2026-10-12T09:00:00"
    assert describe(adapter(vault).fetch(["run-noproto"])[0], config)["protocol"] is None


def test_headline_patterns_are_case_sensitive() -> None:
    summary = {"test.auroc": 0.85, "val.auroc": 0.86}
    assert headline(summary, []) == summary
    assert headline(summary, ["test.*"]) == {"test.auroc": 0.85}
    assert headline(summary, ["TEST.*"]) == {}


def test_config_hash_matches_the_config_hash_command(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = load_config(vault)
    expected = describe(adapter(vault).fetch(["run-c1"])[0], config)["config_hash"]
    assert main(["--vault", str(vault), "config-hash", str(vault / "runs/run-c1/config.yaml")]) == 0
    assert capsys.readouterr().out.strip() == expected


def test_tracker_fetch_cli(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--vault", str(vault), "tracker", "fetch", "run-c1", "run-c2"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [d["run_id"] for d in data] == ["run-c1", "run-c2"]
    assert data[0]["protocol"] == "EVAL-v2" and data[0]["headline"]["test.auroc"] == 0.85


def test_tracker_fetch_cli_errors_exit_2(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--vault", str(vault), "tracker", "fetch", "run-missing"]) == 2
    assert capsys.readouterr().err == "labbrain: run run-missing: config.yaml not found\n"


def _case_insensitive(tmp_path: Path) -> bool:
    (tmp_path / "case").mkdir()
    return (tmp_path / "CASE").exists()


@pytest.mark.parametrize(
    ("data_path", "run_id"),
    [("runs/RUN-C1", "run-c1"), ("RUNS", "run-c1"), ("runs/run-c1", "RUN-C1")],
)
def test_differently_cased_paths_cannot_bypass_the_guard(
    tmp_path: Path, data_path: str, run_id: str
) -> None:
    insensitive = _case_insensitive(tmp_path)
    root = make_vault(tmp_path / "v", MIN_CONFIG + f"data_paths: ['{data_path}']\n")
    copy_runs(root)
    if insensitive:
        with pytest.raises(TrackerError, match="protected data path"):
            adapter(root).fetch([run_id])
    elif run_id != "run-c1":
        # Case-sensitive: the differently-cased run does not exist.
        with pytest.raises(TrackerError, match=r"config.yaml not found$"):
            adapter(root).fetch([run_id])
    else:
        # Case-sensitive: the differently-cased data path names another (absent) path.
        assert adapter(root).fetch([run_id])[0]["run_id"] == "run-c1"


def test_huge_integer_metrics_are_dropped(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    huge = "1" + "0" * 399
    add_run(root, "r1", {"config.yaml": "a: 1\n", "metrics.json": f'{{"big": {huge}, "ok": 2}}'})
    assert adapter(root).fetch(["r1"])[0]["summary"] == {"ok": 2.0}


SECRET_FILES = {"config.yaml": "a: 1\n", "metrics.json": '{"m": 1}', "meta.json": '{"name": "x"}'}


@pytest.mark.parametrize("name", sorted(SECRET_FILES))
def test_symlinked_file_into_a_data_path_is_refused(tmp_path: Path, name: str) -> None:
    secret = tmp_path / "secret"
    root = make_vault(tmp_path / "v", MIN_CONFIG + f"data_paths: ['{secret}']\n")
    write(tmp_path, f"secret/{name}", SECRET_FILES[name])
    add_run(root, "r1", {k: v for k, v in SECRET_FILES.items() if k != name})
    (root / "runs" / "r1" / name).symlink_to(secret / name)
    with pytest.raises(TrackerError, match="protected data path"):
        adapter(root).fetch(["r1"])


@pytest.mark.parametrize("name", sorted(SECRET_FILES))
def test_hard_linked_protected_file_is_refused(tmp_path: Path, name: str) -> None:
    """A data path naming a file is matched by file identity, which a hard link shares."""
    secret = write(tmp_path, f"secret/{name}", SECRET_FILES[name])
    root = make_vault(tmp_path / "v", MIN_CONFIG + f"data_paths: ['{secret}']\n")
    add_run(root, "r1", {k: v for k, v in SECRET_FILES.items() if k != name})
    try:
        os.link(secret, root / "runs" / "r1" / name)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hard links are not supported here ({type(exc).__name__})")
    with pytest.raises(TrackerError, match="protected data path"):
        adapter(root).fetch(["r1"])


def test_unrelated_data_paths_do_not_block_reads(tmp_path: Path) -> None:
    (tmp_path / "elsewhere").mkdir()
    paths = f"['{tmp_path / 'elsewhere'}', '{tmp_path / 'not-yet'}']"
    root = make_vault(tmp_path / "v", MIN_CONFIG + f"data_paths: {paths}\n")
    copy_runs(root)
    assert adapter(root).fetch(["run-nometrics"])[0]["status"] == "unknown"


def test_mixed_key_types_in_a_run_config_still_describe(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    add_run(root, "r1", {"config.yaml": "layers: [{1: a, b: c}]\n"})
    [rec] = adapter(root).fetch(["r1"])
    assert describe(rec, load_config(root))["config_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    "argv",
    [
        ["tracker", "fetch", "run-c1", "run-c2", "run-c1"],
        ["tracker", "diff", "run-c1", "run-c1", "--parent", "EXP-20260910-label-smoothing"],
    ],
)
def test_tracker_commands_refuse_duplicate_runs(
    vault: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert main(["--vault", str(vault), *argv]) == 2
    assert capsys.readouterr().err == "labbrain: run run-c1 given more than once\n"


def test_duplicate_free_text_run_ids_are_not_echoed() -> None:
    from labbrain.trackers import check_run_ids

    name = "Jane" + " " + "Doe"
    with pytest.raises(TrackerError) as info:
        check_run_ids([name, name])
    assert str(info.value) == "invalid run id"
    check_run_ids(["run-c1", "run-c2"])
