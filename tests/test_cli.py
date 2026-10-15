from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest
from fixtures.mutations import BASELINE, CONCEPT, SMOOTHING, replace
from helpers import MIN_CONFIG, make_vault

from labbrain import __version__
from labbrain.cli import main


@pytest.fixture(autouse=True)
def _no_author_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_AUTHOR", raising=False)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert capsys.readouterr().out.strip() == f"labbrain {__version__}"


def test_vault_root_discovery_and_explicit_vault(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run(capsys, "vault", "root") == (0, f"{vault_dir.resolve()}\n", "")
    monkeypatch.delenv("LABBRAIN_VAULT")
    monkeypatch.chdir(vault_dir.parent)
    code, _, err = run(capsys, "vault", "root")
    assert code == 2 and "no vault found" in err
    code, out, _ = run(capsys, "--vault", str(vault_dir), "vault", "root")
    assert (code, out.strip()) == (0, str(vault_dir.resolve()))
    code, out, _ = run(capsys, "lint", "--vault", str(vault_dir))
    assert (code, out) == (0, "0 error(s), 0 warning(s), 0 info\n")


def test_config(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "config", "--key", "tracker.backend")[1] == "local\n"
    code, out, _ = run(capsys, "config")
    assert code == 0 and json.loads(out)["project_slug"] == "toy-classifier"
    assert run(capsys, "config", "--key", "nope")[0] == 2


def test_new_id_and_new(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "new-id", "experiment", "--title", "Label smoothing v2")
    assert (code, out) == (0, "EXP-20261015-label-smoothing-v2\n")
    assert run(capsys, "new-id", "experiment")[0] == 2
    code, out, _ = run(capsys, "new", "decision", "--title", "Pick a tracker", "--author", "alice")
    path = Path(out.strip())
    assert code == 0
    assert path == vault_dir.resolve() / "decisions" / "ADR-20261015-pick-a-tracker.md"
    assert run(capsys, "validate", str(path))[0] == 0
    assert run(capsys, "new", "decision", "--title", "x")[0] == 2
    assert run(capsys, "new", "literature", "--title", "x", "--author", "bob")[0] == 2


def test_validate_exit_codes_and_json(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "validate", str(vault_dir / CONCEPT), "--json")
    assert code == 0 and json.loads(out)["findings"] == []
    replace(vault_dir, CONCEPT, "status: active", "status: archived")
    code, out, _ = run(capsys, "validate", str(vault_dir / CONCEPT), "--json")
    assert code == 1
    assert [f["rule"] for f in json.loads(out)["findings"]] == ["schema"]


def test_lint(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "lint") == (0, "0 error(s), 0 warning(s), 0 info\n", "")
    replace(vault_dir, BASELINE, "status: done", "status: running")
    code, out, _ = run(capsys, "lint", "--format", "github")
    assert code == 1
    assert out.startswith(
        "::error file=experiments/EXP-20260901-baseline.md,line=1,title=frozen-edit::"
    )
    assert run(capsys, "lint", "--rule", "orphan")[0] == 0
    code, _, err = run(capsys, "lint", "--rule", "nope")
    assert code == 2 and "unknown lint rule" in err


def test_sync(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    replace(
        vault_dir,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )
    code, out, _ = run(capsys, "sync", "--dry-run")
    assert code == 0 and "would update" in out
    assert "status: done" in (vault_dir / BASELINE).read_text()
    code, out, _ = run(capsys, "sync")
    assert code == 0 and "updated:" in out
    assert "status: superseded" in (vault_dir / BASELINE).read_text()
    assert json.loads(run(capsys, "sync", "--json")[1])["findings"] == []


def test_index_and_log(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "index", "--check")[0] == 0
    replace(vault_dir, CONCEPT, 'title: "Label smoothing and calibration"', 'title: "Renamed"')
    assert run(capsys, "index", "--check")[0] == 1
    assert run(capsys, "index")[1] == "index.md updated\n"
    assert run(capsys, "index", "--check")[0] == 0
    code, out, _ = run(capsys, "log", "exp-log: logged a run", "--author", "alice")
    assert code == 0
    assert Path(out.strip()).read_text().endswith("- 12:00 [alice] exp-log: logged a run\n")


def test_phi_outputs_never_echo_identifiers(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    value = str(random.Random(7).randrange(10_000_000, 99_999_999))
    path = vault_dir / "manuscripts" / "draft.md"
    path.parent.mkdir()
    path.write_text(f"Patient MRN {value}.\n")
    for args in (
        ("phi-scan", str(path)),
        ("phi-scan", str(vault_dir), "--json"),
        ("validate", str(path), "--format", "github"),
        ("lint", "--json"),
    ):
        code, out, err = run(capsys, *args)
        assert code == 1, args
        assert value not in out + err, args


def test_phi_scan_outside_a_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)
    (tmp_path / "notes.md").write_text("n = 4 patients\n")
    code, out, _ = run(capsys, "phi-scan", str(tmp_path))
    assert code == 1 and "[phi-small-cell]" in out
    assert run(capsys, "phi-scan", str(tmp_path / "missing"))[0] == 2


def test_list_links_config_hash_schema(
    vault_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "list", "--type", "experiment", "--json")
    assert code == 0
    assert [r["id"] for r in json.loads(out)] == [
        "EXP-20260901-baseline",
        "EXP-20260910-label-smoothing",
    ]
    assert run(capsys, "links", "CLM-20261001-median-auroc", "--in")[1] == (
        "in\tHO-20261014-1420-claude\nin\tlabel-smoothing-calibration\n"
    )
    assert run(capsys, "links", "nope")[0] == 2
    run_config = tmp_path / "run.yaml"
    run_config.write_text("train:\n  lr: 0.001\n  seed: 3\n")
    code, out, _ = run(capsys, "config-hash", str(run_config))
    assert code == 0 and out.startswith("sha256:")
    assert json.loads(run(capsys, "schema", "claim")[1])["title"] == "ClaimNote"


def test_config_problems_exit_2_and_version_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = make_vault(tmp_path / "bad", MIN_CONFIG + "min_cell_size: 1\n")
    monkeypatch.setenv("LABBRAIN_VAULT", str(bad))
    code, _, err = run(capsys, "lint")
    assert code == 2 and "min_cell_size" in err
    newer = make_vault(tmp_path / "newer", MIN_CONFIG + "engine_min_version: 99.0.0\n")
    monkeypatch.setenv("LABBRAIN_VAULT", str(newer))
    _, _, err = run(capsys, "lint")
    assert "engine_min_version 99.0.0" in err


def test_cli_import_is_lightweight() -> None:
    probe = (
        "import sys, labbrain.cli; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('pydantic', 'ruamel', 'yaml')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[]"


def test_module_entry_point() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "labbrain", "--version"], capture_output=True, text=True
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"labbrain {__version__}"


def test_explicit_non_vault_is_a_usage_error_for_fallback_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """phi-scan and config-hash fall back to defaults only when discovery finds no vault."""
    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)
    (tmp_path / "notes.md").write_text("Nothing here.\n")
    run_config = tmp_path / "run.yaml"
    run_config.write_text("lr: 0.001\n")
    not_a_vault = tmp_path / "elsewhere"
    not_a_vault.mkdir()
    for args in (("phi-scan", str(tmp_path / "notes.md")), ("config-hash", str(run_config))):
        assert run(capsys, *args)[0] == 0, args
        code, _, err = run(capsys, "--vault", str(not_a_vault), *args)
        assert code == 2 and "--vault points to" in err, args
        monkeypatch.setenv("LABBRAIN_VAULT", str(not_a_vault))
        code, _, err = run(capsys, *args)
        assert code == 2 and "LABBRAIN_VAULT points to" in err, args
        monkeypatch.delenv("LABBRAIN_VAULT")


def test_links_output_never_echoes_free_text_targets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_query import probe_vault

    root, secrets = probe_vault(tmp_path / "v")
    monkeypatch.setenv("LABBRAIN_VAULT", str(root))
    for args in (("links", "probe"), ("links", "probe", "--out", "--json")):
        code, out, err = run(capsys, *args)
        assert code == 0 and "<not a valid note ID>" in out, args
        assert not any(secret in out + err for secret in secrets), args


def test_unreadable_allowlist_exits_2_without_traceback_or_content(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (vault_dir / ".labbrain" / "phi-allow.yaml").write_bytes(b"- file: \xff\xfe sentinelvalue\n")
    for args in (("phi-scan", str(vault_dir)), ("lint",)):
        code, out, err = run(capsys, *args)
        assert code == 2, args
        assert "phi-allow.yaml" in err and "Traceback" not in err, args
        assert "sentinelvalue" not in out + err, args


def test_unexpected_errors_are_reported_without_details(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from labbrain import cli

    def boom(args: object) -> int:
        raise RuntimeError("secret detail 31415926")

    monkeypatch.setattr(cli, "cmd_schema", boom)
    code, out, err = run(capsys, "schema")
    assert (code, out, err) == (2, "", "labbrain: internal error (RuntimeError)\n")

    def broken_pipe(args: object) -> int:
        raise BrokenPipeError

    monkeypatch.setattr(cli, "cmd_schema", broken_pipe)
    assert run(capsys, "schema") == (0, "", "")


def test_every_vault_command_warns_once_about_engine_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    newer = make_vault(tmp_path / "newer", MIN_CONFIG + "engine_min_version: 99.0.0\n")
    first = newer / "concepts" / "a.md"
    first.parent.mkdir()
    first.write_text("Text.\n")
    (newer / "concepts" / "b.md").write_text("Text.\n")
    run_config = tmp_path / "run.yaml"
    run_config.write_text("lr: 0.001\n")
    monkeypatch.setenv("LABBRAIN_VAULT", str(newer))
    for args in (
        ("vault", "root"),
        ("config",),
        ("new-id", "experiment", "--title", "x"),
        ("validate", str(first), str(newer / "concepts" / "b.md")),
        ("sync",),
        ("index", "--check"),
        ("log", "exp-log: ran", "--author", "alice"),
        ("lint",),
        ("phi-scan", str(newer / "concepts")),
        ("list",),
        ("config-hash", str(run_config)),
    ):
        err = run(capsys, *args)[2]
        assert err.count("engine_min_version 99.0.0") == 1, (args, err)
