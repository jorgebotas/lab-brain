"""Shared test helpers. Importable because pyproject sets pythonpath = ["tests"]."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from labbrain.notes import render_note
from labbrain.schema import DEFAULT_STATUS, REQUIRED_SECTIONS

MIN_CONFIG = "project_name: Toy\nproject_slug: toy\nlab_members: [alice, bob]\n"


def make_vault(root: Path, config: str = MIN_CONFIG) -> Path:
    (root / ".labbrain").mkdir(parents=True, exist_ok=True)
    (root / ".labbrain" / "config.yaml").write_text(config)
    return root


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def body_for(note_type: str, text: str = "Text.") -> str:
    return "".join(f"## {section}\n\n{text}\n\n" for section in REQUIRED_SECTIONS[note_type])


def note_text(note_id: str, note_type: str, body: str | None = None, **fields: Any) -> str:
    data: dict[str, Any] = {
        "id": note_id,
        "type": note_type,
        "title": fields.pop("title", note_id),
        "created": fields.pop("created", date(2026, 10, 1)),
        "updated": fields.pop("updated", date(2026, 10, 1)),
        "author": fields.pop("author", "alice"),
        "status": fields.pop("status", DEFAULT_STATUS[note_type]),
    }
    data.update(fields)
    return render_note(data, body_for(note_type) if body is None else body)


FIXTURE = Path(__file__).parent / "fixtures" / "valid"
RUNS_FIXTURE = Path(__file__).parent / "fixtures" / "runs"


def copy_runs(vault: Path) -> Path:
    """Copy the synthetic tracker runs to `<vault>/runs`, the default local runs_dir."""
    return Path(shutil.copytree(RUNS_FIXTURE, vault / "runs"))


PINNED_NOW = "2026-10-15T12:00:00"
TODAY = date(2026, 10, 15)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def commit_all(cwd: Path, message: str = "fixture") -> None:
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "--no-verify", "--allow-empty", "-m", message)


def copy_fixture(dest: Path) -> Path:
    shutil.copytree(FIXTURE, dest)
    return dest


HOOK_FIXTURES = Path(__file__).parent / "fixtures" / "hooks"
_HOOK_OVERRIDES = ("tool_input", "tool_name")


def _substitute(value: Any, subs: dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, text in subs.items():
            value = value.replace("{" + key + "}", text)
        return value
    if isinstance(value, dict):
        return {k: _substitute(v, subs) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, subs) for v in value]
    return value


def hook_payload(name: str, **subs: Any) -> bytes:
    """A recorded hook payload from tests/fixtures/hooks/<name>.json, as stdin bytes.

    Each `{key}` placeholder (cwd, path, command, content, old, new, source) in any string
    is replaced by str(value); placeholders not given stay literal. `tool_input=` and
    `tool_name=` replace those top-level fields after substitution.
    """
    overrides = {key: subs.pop(key) for key in _HOOK_OVERRIDES if key in subs}
    data = json.loads((HOOK_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    data = _substitute(data, {key: str(value) for key, value in subs.items()})
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False).encode("utf-8")
