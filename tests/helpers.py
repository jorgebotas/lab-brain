"""Shared test helpers. Importable because pyproject sets pythonpath = ["tests"]."""

from __future__ import annotations

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
