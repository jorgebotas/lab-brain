"""SessionStart: index.md is regenerated and the short brief goes to stdout."""

from __future__ import annotations

import secrets
import time
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, commit_all, git, hook_payload, make_vault, note_text, write

from labbrain import index
from labbrain.hooks.entry import run_hook
from labbrain.hooks.payload import Payload, parse_payload
from labbrain.hooks.session import session_start
from labbrain.vault import Vault

CONFIG_ERROR = (
    "lab-brain: vault config error; ask the user to fix .labbrain/config.yaml "
    "(`labbrain lint` shows the problem)\n"
)
PROTECTED = MIN_CONFIG + "data_paths: [data]\n"


def payload(cwd: Path, source: str = "startup") -> Payload:
    return parse_payload(hook_payload("session_start", cwd=cwd, source=source))


def toy_vault(root: Path, config: str = MIN_CONFIG) -> Path:
    make_vault(root, config)
    write(root, "ideas/inbox/IDEA-20261001-alpha.md", note_text("IDEA-20261001-alpha", "idea"))
    return root


def test_no_vault_silent(tmp_path: Path) -> None:
    assert session_start(payload(tmp_path), {}) == (0, "", "")


def test_brief_printed_and_index_regenerated(tmp_path: Path) -> None:
    root = toy_vault(tmp_path / "v")
    code, out, err = session_start(payload(root), {})
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert 1 <= len(lines) <= 4
    assert lines[0].startswith("Toy · engine ")
    assert "Open ideas 1" in out
    assert out.endswith("\n")
    assert (root / "index.md").read_text(encoding="utf-8") == index.render(Vault.load(root))


def test_version_warning_line(tmp_path: Path) -> None:
    root = toy_vault(tmp_path / "v", MIN_CONFIG + "engine_min_version: 99.0.0\n")
    code, out, _ = session_start(payload(root), {})
    lines = out.splitlines()
    assert code == 0
    assert len(lines) <= 4
    assert lines[1].startswith("warning: labbrain ")
    assert "99.0.0" in lines[1]


def test_broken_config_one_line(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v", "project_name: [unclosed\n")
    assert session_start(payload(root), {}) == (0, CONFIG_ERROR, "")
    assert not (root / "index.md").exists()


def test_index_failure_still_prints_brief(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = toy_vault(tmp_path / "v")

    def fail(_: Vault) -> bool:
        raise OSError("SECRET")

    monkeypatch.setattr(index, "write", fail)
    code, out, err = session_start(payload(root), {})
    assert (code, err) == (0, "")
    assert out.startswith("Toy · engine ")
    assert out.splitlines()[-1].endswith("Lint errors 0 · index.md not regenerated")
    assert "SECRET" not in out


def test_index_failure_with_version_warning_stays_four_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = toy_vault(tmp_path / "v", MIN_CONFIG + "engine_min_version: 99.0.0\n")

    def fail(_: Vault) -> bool:
        raise OSError("SECRET")

    monkeypatch.setattr(index, "write", fail)
    code, out, _ = session_start(payload(root), {})
    lines = out.splitlines()
    assert code == 0
    assert len(lines) == 4
    assert lines[1].startswith("warning: ")
    assert lines[-1].endswith(" · index.md not regenerated")
    assert out.endswith("\n")


def handoff_vault(root: Path, title: str) -> Path:
    toy_vault(root)
    hid = "HO-20261014-1420-claude"
    write(root, f"handoffs/{hid}.md", note_text(hid, "handoff", title=title))
    return root


def test_handoff_title_digits_redacted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from labbrain.cli import main

    digits = str(secrets.randbelow(90_000_000) + 10_000_000)
    root = handoff_vault(tmp_path / "v", f"Patient {digits}")
    code, out, _ = session_start(payload(root), {})
    assert code == 0
    assert "Last handoff: HO-20261014-1420-claude  Patient" in out
    assert digits not in out
    capsys.readouterr()
    for argv in (["brief", "--short"], ["brief"]):
        assert main(["--vault", str(root), *argv]) == 0
        cli_out = capsys.readouterr().out
        assert "HO-20261014-1420-claude  Patient" in cli_out
        assert digits not in cli_out, argv


def test_plain_handoff_title_shown(tmp_path: Path) -> None:
    root = handoff_vault(tmp_path / "v", "Registered the headline AUROC claim")
    _, out, _ = session_start(payload(root), {})
    assert "Last handoff: HO-20261014-1420-claude  Registered the headline AUROC claim\n" in out


def test_subfolder_env_relative_vault(tmp_path: Path) -> None:
    project = tmp_path / "project"
    toy_vault(project / "brain")
    cwd = project / "src"
    cwd.mkdir()
    env = {"LABBRAIN_VAULT": "brain", "CLAUDE_PROJECT_DIR": str(project)}
    code, out, _ = session_start(payload(cwd), env)
    assert code == 0
    assert out.startswith("Toy · engine ")
    assert (project / "brain" / "index.md").is_file()


def test_entry_puts_brief_on_stdout(tmp_path: Path) -> None:
    root = toy_vault(tmp_path / "v")
    code, out, err = run_hook("session-start", hook_payload("session_start", cwd=root), {})
    assert (code, err) == (0, "")
    assert out.startswith("Toy · engine ")


@pytest.mark.slow
def test_short_brief_under_3s_on_300_notes(tmp_path: Path) -> None:
    from test_perf import build_vault

    root = build_vault(tmp_path / "big", per_type=100)  # 302 notes
    (root / ".labbrain" / "config.yaml").write_text(PROTECTED)
    git(root, "init", "-q", "-b", "main")
    commit_all(root)
    p = payload(root)

    def once() -> tuple[float, str]:
        start = time.perf_counter()
        code, out, _ = session_start(p, {})
        assert code == 0
        return time.perf_counter() - start, out

    once()  # untimed warm-up: first-open file scanning and the first index.md write
    wall, out = min(once() for _ in range(2))
    assert len(out.splitlines()) <= 4
    assert wall < 3.0, f"session-start took {wall:.2f}s on 300 notes"
