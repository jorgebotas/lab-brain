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


def test_normal_config_hashes_are_unchanged() -> None:
    import hashlib

    config = {"train": {"lr": 0.001, "epochs": 10}, "model": "resnet", "tags": ["a", "b"]}
    flat = {"model": "resnet", "tags": ["a", "b"], "train.epochs": 10, "train.lr": 0.001}
    payload = json.dumps(flat, sort_keys=True, separators=(",", ":"), default=str)
    expected = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert config_hash(config, []) == expected


def test_mixed_key_types_inside_lists_still_hash() -> None:
    mixed = {"layers": [{1: "a", "b": "c"}]}
    assert config_hash(mixed, []).startswith("sha256:")
    assert config_hash(mixed, []) == config_hash({"layers": [{"b": "c", 1: "a"}]}, [])
    assert config_hash(mixed, []) != config_hash({"layers": [{1: "a", "b": "d"}]}, [])


def test_flatten_refuses_colliding_keys() -> None:
    with pytest.raises(ValueError, match="collide"):
        flatten({"a.b": 999, "a": {"b": 2}})


@pytest.mark.parametrize(
    "text",
    [
        "when: 2026-13-45\n",
        "a: &x {b: *x}\n",
        "a: " + "[" * 5000 + "]" * 5000 + "\n",
        'url: "x\\udc85"\n',
    ],
    ids=["impossible-date", "recursive-alias", "deep-nesting", "lone-surrogate"],
)
def test_load_run_config_refuses_odd_yaml(tmp_path: Path, text: str) -> None:
    (tmp_path / "c.yaml").write_text(text)
    with pytest.raises(ValueError) as info:
        load_run_config(tmp_path / "c.yaml")
    assert str(info.value) == "cannot read run config c.yaml"


def test_config_hash_cli_refuses_colliding_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from labbrain.cli import main

    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "c.yaml").write_text("a.b: 999\na:\n  b: 2\n")
    assert main(["config-hash", str(tmp_path / "c.yaml")]) == 2
    err = capsys.readouterr().err
    assert err == "labbrain: run config c.yaml has keys that collide when flattened\n"
    assert "999" not in err
