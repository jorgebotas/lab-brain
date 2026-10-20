"""PostToolUse: the write validator reports errors (exit 2) and is silent otherwise."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import pytest
from helpers import MIN_CONFIG, hook_payload, make_vault, note_text, write

from labbrain.hooks.entry import run_hook
from labbrain.hooks.payload import Payload, parse_payload
from labbrain.hooks.post import post_tool_use

HEADER = "lab-brain validator: fix these before continuing:\n"
PROTECTED = MIN_CONFIG + "data_paths: [data]\n"


def payload(cwd: Path, path: Path | str, **subs: Any) -> Payload:
    return parse_payload(hook_payload("post_write", cwd=cwd, path=path, content="x", **subs))


def sentinel() -> str:
    return "zq" + secrets.token_hex(6)


def idea(root: Path, name: str = "IDEA-20261001-alpha", **fields: Any) -> Path:
    return write(root, f"ideas/inbox/{name}.md", note_text(name, "idea", **fields))


def test_schema_error_reported_exit_2(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    title, tag = sentinel(), sentinel()
    path = idea(root, title=title, tags=[tag])
    text = path.read_text().replace("author: alice\n", "")
    path.write_text(text)
    code, err = post_tool_use(payload(root, path), {})
    assert code == 2
    assert err.startswith(HEADER)
    assert "ideas/inbox/IDEA-20261001-alpha.md" in err
    assert "[schema]" in err
    assert "error(s)" in err
    assert title not in err and tag not in err
    assert str(tmp_path) not in err


def test_clean_write_silent(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    path = idea(root)
    assert post_tool_use(payload(root, path), {}) == (0, "")


def test_warning_only_silent(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    text = note_text("topic-beta", "concept", body="No sections.\n", sources=[])
    path = write(root, "concepts/topic-beta.md", text)
    from labbrain.validate import validate_path

    severities = {f.severity for f in validate_path(path, vault=root)}
    assert severities == {"warning"}  # the case really is warning-only
    assert post_tool_use(payload(root, path), {}) == (0, "")


def test_outside_vault_silent(tmp_path: Path) -> None:
    loose = write(tmp_path / "loose", "notes/IDEA-20261001-x.md", "no frontmatter\n")
    assert post_tool_use(payload(tmp_path, loose), {}) == (0, "")


def test_phi_in_written_note_reported(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v", PROTECTED)
    value = str(secrets.randbelow(90_000_000) + 10_000_000)
    path = idea(root, body=f"## Idea\n\nPatient MRN {value} was excluded.\n")
    code, err = post_tool_use(payload(root, path), {})
    assert code == 2
    assert "[phi]" in err and "phi-mrn" in err
    assert value not in err


def test_labbrain_vault_env_does_not_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_vault(tmp_path / "v")
    other = make_vault(tmp_path / "other")
    path = idea(root)
    path.write_text(path.read_text().replace("author: alice\n", ""))
    env = {"LABBRAIN_VAULT": str(other), "CLAUDE_PROJECT_DIR": str(other)}
    monkeypatch.setenv("LABBRAIN_VAULT", str(other))
    code, err = post_tool_use(payload(other, path), env)
    assert code == 2
    assert "ideas/inbox/IDEA-20261001-alpha.md" in err


@pytest.mark.parametrize(
    ("tool", "key"),
    [("Edit", "file_path"), ("MultiEdit", "file_path"), ("NotebookEdit", "notebook_path")],
)
def test_other_write_tools_validated(tmp_path: Path, tool: str, key: str) -> None:
    root = make_vault(tmp_path / "v")
    path = idea(root)
    path.write_text(path.read_text().replace("author: alice\n", ""))
    p = payload(root, path, tool_name=tool, tool_input={key: str(path)})
    assert post_tool_use(p, {})[0] == 2


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [("Read", None), ("Write", {}), ("Write", {"file_path": 3}), ("Write", {"file_path": ""})],
)
def test_irrelevant_calls_silent(tmp_path: Path, tool: str, tool_input: Any) -> None:
    root = make_vault(tmp_path / "v")
    path = idea(root)
    path.write_text(path.read_text().replace("author: alice\n", ""))
    inp = {"file_path": str(path)} if tool_input is None else tool_input
    assert post_tool_use(payload(root, path, tool_name=tool, tool_input=inp), {}) == (0, "")


def test_relative_path_taken_from_cwd(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    path = idea(root)
    path.write_text(path.read_text().replace("author: alice\n", ""))
    p = payload(root, path, tool_input={"file_path": "ideas/inbox/IDEA-20261001-alpha.md"})
    assert post_tool_use(p, {})[0] == 2


def test_uncanonical_path_silent(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    p = payload(root, root, tool_input={"file_path": str(root / "a\0b.md")})
    assert post_tool_use(p, {}) == (0, "")


def test_entry_reports_on_stderr(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    path = idea(root)
    path.write_text(path.read_text().replace("author: alice\n", ""))
    stdin = hook_payload("post_write", cwd=root, path=path, content="x")
    code, out, err = run_hook("post-tool-use", stdin, {})
    assert (code, out) == (2, "")
    assert err.startswith(HEADER)
