"""Config diffs between run groups, and `labbrain tracker diff`."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import copy_runs, note_text, write

from labbrain.cli import main
from labbrain.experiments import (
    RecordError,
    config_diff,
    parent_run_ids,
    render_runs,
    render_setup,
    split_common,
)
from labbrain.vault import Vault

PARENT = "EXP-20260910-label-smoothing"
IGNORE = ["seed", "*.seed"]

EXPECTED_SETUP = """\
Config diff against [[EXP-20260910-label-smoothing]] (hash_ignore keys omitted):

| key | parent | this |
| --- | --- | --- |
| model.dropout | — | 0.1 |
| optim.lr | 0.001 | 0.0003 |

Varied across these runs: data.fold.
"""


def test_split_common() -> None:
    configs = [{"a": 1, "b": 2, "seed": 1}, {"a": 1, "b": 3, "seed": 2}]
    assert split_common(configs, IGNORE) == ({"a": 1}, ["b"])
    assert split_common([{"a": 1}, {"a": 1, "c": 5}], []) == ({"a": 1}, ["c"])
    assert split_common([], []) == ({}, [])


def test_added_removed_changed() -> None:
    diff = config_diff(
        PARENT, [{"lr": 0.001, "old": 1, "same": 2}], [{"lr": 0.0003, "new": 0.1, "same": 2}], []
    )
    assert diff.added == {"new": 0.1}
    assert diff.removed == {"old": 1}
    assert diff.changed == {"lr": (0.001, 0.0003)}
    assert not diff.empty


def test_varied_keys_stay_out_of_added_and_removed() -> None:
    parent = [{"k": 1, "p": 1}, {"k": 1, "p": 2}]
    child = [{"k": 1, "f": 0}, {"k": 1, "f": 1}]
    diff = config_diff(PARENT, parent, child, [])
    assert (diff.added, diff.removed, diff.changed) == ({}, {}, {})
    assert diff.varied_here == ["f"] and diff.varied_parent == ["p"]


def test_hash_ignore_keys_are_dropped() -> None:
    diff = config_diff(PARENT, [{"a": 1, "seed": 1}], [{"a": 1, "seed": 2}], IGNORE)
    assert diff.empty and diff.varied_here == []


def test_render_setup_table() -> None:
    diff = config_diff(
        PARENT,
        [{"optim.lr": 0.001, "data.fold": 0}],
        [
            {"optim.lr": 0.0003, "model.dropout": 0.1, "data.fold": 0},
            {"optim.lr": 0.0003, "model.dropout": 0.1, "data.fold": 1},
        ],
        [],
    )
    assert render_setup(diff) == EXPECTED_SETUP


def test_render_escapes_pipes_and_marks_removed_keys() -> None:
    diff = config_diff(PARENT, [{"a|b": "x|y", "gone": True}], [{"a|b": "z"}], [])
    text = render_setup(diff)
    assert '| a\\|b | "x\\|y" | "z" |' in text
    assert "| gone | true | — |" in text


def test_render_without_differences() -> None:
    diff = config_diff(PARENT, [{"a": 1}, {"a": 1, "p": 2}], [{"a": 1}], [])
    assert render_setup(diff) == (
        "Same config as [[EXP-20260910-label-smoothing]] (hash_ignore keys omitted).\n"
        "\n"
        "Varied across the parent's runs: p.\n"
    )


def test_render_runs() -> None:
    assert render_runs(["run-a", "run-b"], ["data.fold"]) == (
        "Runs: run-a, run-b.\nVaried across these runs: data.fold.\n"
    )
    assert render_runs(["run-a"], []) == "Runs: run-a.\n"


def test_parent_run_ids(vault_dir: Path) -> None:
    vault = Vault.load(vault_dir)
    assert parent_run_ids(vault, PARENT) == ["run-002"]
    with pytest.raises(RecordError, match="^no experiment with ID EXP-20990101-nope$"):
        parent_run_ids(vault, "EXP-20990101-nope")
    with pytest.raises(
        RecordError, match="^no experiment with ID IDEA-20261010-smoothing-schedule$"
    ):
        parent_run_ids(vault, "IDEA-20261010-smoothing-schedule")
    write(
        vault_dir,
        "experiments/EXP-20261015-planned.md",
        note_text("EXP-20261015-planned", "experiment"),
    )
    with pytest.raises(RecordError, match="^parent EXP-20261015-planned has no run ids$"):
        parent_run_ids(Vault.load(vault_dir), "EXP-20261015-planned")


def test_unknown_parent_ids_are_not_echoed(vault_dir: Path) -> None:
    with pytest.raises(RecordError) as info:
        parent_run_ids(Vault.load(vault_dir), "Jane Doe 48151623")
    assert "48151623" not in str(info.value)


def test_tracker_diff_cli(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    copy_runs(vault_dir)
    assert main(["tracker", "diff", "run-c1", "run-c2", "--parent", PARENT]) == 0
    assert capsys.readouterr().out == EXPECTED_SETUP


def test_tracker_diff_cli_unknown_parent(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy_runs(vault_dir)
    assert main(["tracker", "diff", "run-c1", "--parent", "EXP-20990101-nope"]) == 2
    assert "no experiment with ID" in capsys.readouterr().err
