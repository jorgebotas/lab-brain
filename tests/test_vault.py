from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, body_for, make_vault, note_text, write

from labbrain.vault import (
    ConfigError,
    Vault,
    VaultNotFound,
    find_root,
    load_config,
    now,
    today,
    version_warning,
)


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)


def test_find_root_walks_up(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    deep = root / "experiments" / "deep"
    deep.mkdir(parents=True)
    assert find_root(start=deep) == root.resolve()


def test_find_root_env_and_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = make_vault(tmp_path / "a")
    b = make_vault(tmp_path / "b")
    monkeypatch.setenv("LABBRAIN_VAULT", str(a))
    assert find_root(start=b) == a.resolve()
    assert find_root(start=b, explicit=b) == b.resolve()


def test_find_root_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(VaultNotFound, match="--vault"):
        find_root(start=tmp_path)
    monkeypatch.setenv("LABBRAIN_VAULT", str(tmp_path))
    with pytest.raises(VaultNotFound, match="LABBRAIN_VAULT"):
        find_root()


def test_now_honours_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABBRAIN_NOW", "2026-10-15T12:00:00")
    assert now() == datetime(2026, 10, 15, 12, 0)
    assert today() == date(2026, 10, 15)
    monkeypatch.setenv("LABBRAIN_NOW", "yesterday")
    with pytest.raises(ConfigError):
        now()


def test_config_defaults(tmp_path: Path) -> None:
    cfg = load_config(make_vault(tmp_path))
    assert cfg.min_cell_size == 11
    assert cfg.agents == ["claude", "codex", "gemini"]
    assert cfg.id_prefixes["experiment"] == "EXP"
    assert cfg.protected_data is True
    assert cfg.tracker.backend == "local"
    assert cfg.inbox_max_days == 30


def test_config_prefix_override_merges(tmp_path: Path) -> None:
    cfg = load_config(make_vault(tmp_path, MIN_CONFIG + "id_prefixes: {experiment: RUN}\n"))
    assert cfg.id_prefixes["experiment"] == "RUN"
    assert cfg.id_prefixes["claim"] == "CLM"


def test_config_errors_do_not_echo_values(tmp_path: Path) -> None:
    root = make_vault(tmp_path, MIN_CONFIG + "min_cell_size: 'x48151623'\n")
    with pytest.raises(ConfigError) as info:
        load_config(root)
    assert "min_cell_size" in str(info.value)
    assert "48151623" not in str(info.value)


def test_config_errors_mask_dict_keys(tmp_path: Path) -> None:
    root = make_vault(tmp_path, MIN_CONFIG + "id_prefixes: {k48151623: [1]}\n")
    with pytest.raises(ConfigError) as info:
        load_config(root)
    assert "id_prefixes.<key>" in str(info.value)
    assert "48151623" not in str(info.value)
    root = make_vault(tmp_path, MIN_CONFIG + "48151623: v\n")
    with pytest.raises(ConfigError) as info:
        load_config(root)
    assert "48151623" not in str(info.value)


def test_config_not_utf8_is_config_error(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    (root / ".labbrain" / "config.yaml").write_bytes(b"project_name: \xff\n")
    with pytest.raises(ConfigError, match="UTF-8"):
        load_config(root)


@pytest.mark.parametrize("text", ["- a\n", "project_name: [oops\n"])
def test_config_must_be_a_valid_mapping(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(make_vault(tmp_path, text))


def test_authorship(tmp_path: Path) -> None:
    cfg = load_config(make_vault(tmp_path / "a"))
    assert cfg.author_allowed("alice") and cfg.author_allowed("claude")
    assert not cfg.author_allowed("mallory") and not cfg.author_allowed("")
    assert cfg.is_agent("claude") and not cfg.is_agent("alice")
    open_cfg = load_config(make_vault(tmp_path / "b", "project_name: T\nproject_slug: t\n"))
    assert open_cfg.author_allowed("mallory")


def test_version_warning(tmp_path: Path) -> None:
    assert version_warning(load_config(make_vault(tmp_path / "a"))) is None
    newer = load_config(make_vault(tmp_path / "b", MIN_CONFIG + "engine_min_version: 99.0.0\n"))
    warning = version_warning(newer)
    assert warning is not None and "99.0.0" in warning


def test_vault_graph(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "experiments/EXP-20261001-a.md", note_text("EXP-20261001-a", "experiment"))
    write(
        root,
        "concepts/topic.md",
        note_text(
            "topic",
            "concept",
            sources=["EXP-20261001-a"],
            body=body_for("concept", "See [[EXP-20261001-a]] and ![[figures/x.png]]."),
        ),
    )
    write(root, "ideas/inbox/IDEA-20261001-x.md", note_text("IDEA-20261001-x", "idea"))
    write(root, "ideas/archive/IDEA-20261001-x.md", note_text("IDEA-20261001-x", "idea"))
    write(root, "experiments/README.md", "Append-only.\n")
    vault = Vault.load(root)
    assert sorted(vault.notes) == ["EXP-20261001-a", "IDEA-20261001-x", "topic"]
    assert sorted(vault.by_rel) == [
        "concepts/topic.md",
        "experiments/EXP-20261001-a.md",
        "ideas/archive/IDEA-20261001-x.md",
        "ideas/inbox/IDEA-20261001-x.md",
    ]
    assert vault.inbound == {"EXP-20261001-a": {"topic"}}
    assert vault.outbound == {"topic": {"EXP-20261001-a"}}
    assert list(vault.duplicates) == ["IDEA-20261001-x"]
    assert len(vault.duplicates["IDEA-20261001-x"]) == 2
    assert [n.stem for n in vault.of_type("experiment")] == ["EXP-20261001-a"]
    assert vault.get("missing") is None


def test_invalid_notes_still_register_and_link(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "experiments/EXP-20261001-a.md", note_text("EXP-20261001-a", "experiment"))
    write(
        root,
        "concepts/broken.md",
        note_text("broken", "concept", status="bogus", sources=["EXP-20261001-a"]),
    )
    write(root, "concepts/unparsable.md", "---\ntitle: [oops\n---\nSee [[EXP-20261001-a]].\n")
    vault = Vault.load(root)
    assert vault.inbound["EXP-20261001-a"] == {"broken", "unparsable"}
    assert vault.notes["unparsable"].data is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read chmod 000 files")
def test_unreadable_note_does_not_abort_load(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "experiments/EXP-20261001-a.md", note_text("EXP-20261001-a", "experiment"))
    locked = write(root, "concepts/locked.md", note_text("locked", "concept"))
    locked.chmod(0)
    try:
        vault = Vault.load(root)
    finally:
        locked.chmod(0o644)
    assert sorted(vault.notes) == ["EXP-20261001-a", "locked"]
    assert vault.notes["locked"].errors == ["cannot read file"]
    assert vault.notes["EXP-20261001-a"].data is not None
