from __future__ import annotations

import json
from pathlib import Path

import pytest

from labbrain.confighash import config_hash, flatten, load_run_config
from labbrain.vault import DEFAULT_HASH_IGNORE


def test_flatten() -> None:
    assert flatten({"a": {"b": 1, "c": {"d": 2}}, "e": [1, 2], "f": {}}) == {
        "a.b": 1,
        "a.c.d": 2,
        "e": [1, 2],
        "f": {},
    }


def test_hash_ignores_key_order_and_nesting_style() -> None:
    nested = {"train": {"lr": 0.001, "epochs": 10}, "model": "resnet"}
    dotted = {"model": "resnet", "train.epochs": 10, "train.lr": 0.001}
    assert config_hash(nested, []) == config_hash(dotted, [])


def test_hash_ignore_patterns() -> None:
    first = {"train": {"lr": 0.001, "seed": 1}, "seed": 7, "output_dir": "/tmp/a"}
    second = {"train": {"lr": 0.001, "seed": 2}, "seed": 8, "output_dir": "/tmp/b"}
    assert config_hash(first, DEFAULT_HASH_IGNORE) == config_hash(second, DEFAULT_HASH_IGNORE)
    assert config_hash(first, []) != config_hash(second, [])


def test_value_change_changes_hash_and_format() -> None:
    a = config_hash({"lr": 0.001}, [])
    b = config_hash({"lr": 0.002}, [])
    assert a != b
    assert a.startswith("sha256:") and len(a) == len("sha256:") + 64


def test_load_run_config(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("train:\n  lr: 0.001\n")
    (tmp_path / "c.json").write_text(json.dumps({"train": {"lr": 0.001}}))
    assert load_run_config(tmp_path / "c.yaml") == load_run_config(tmp_path / "c.json")
    (tmp_path / "bad.yaml").write_text("- a\n")
    with pytest.raises(ValueError):
        load_run_config(tmp_path / "bad.yaml")
    with pytest.raises(ValueError):
        load_run_config(tmp_path / "missing.yaml")


def test_load_run_config_non_utf8_is_sanitized_value_error(tmp_path: Path) -> None:
    (tmp_path / "latin.yaml").write_bytes(b"name: caf\xe9\n")
    with pytest.raises(ValueError) as info:
        load_run_config(tmp_path / "latin.yaml")
    assert str(info.value) == "cannot read run config latin.yaml"
