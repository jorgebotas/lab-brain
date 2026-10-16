"""Vault layout: folder names, note types, skip lists, and note-path predicates.

Pure standard library so the CLI can import it without pulling in pydantic.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePosixPath

NOTE_TYPES: tuple[str, ...] = (
    "experiment",
    "protocol",
    "claim",
    "idea",
    "concept",
    "decision",
    "literature",
    "handoff",
    "dataset",
)

# Where `labbrain new` puts each type. Ideas start in the inbox.
TYPE_FOLDERS: dict[str, str] = {
    "experiment": "experiments",
    "protocol": "protocols",
    "claim": "claims",
    "idea": "ideas/inbox",
    "concept": "concepts",
    "decision": "decisions",
    "literature": "literature",
    "handoff": "handoffs",
    "dataset": "datasets",
}

# Top-level folders that hold notes; searched recursively.
NOTE_FOLDERS: tuple[str, ...] = (
    "experiments",
    "protocols",
    "claims",
    "ideas",
    "concepts",
    "decisions",
    "literature",
    "handoffs",
    "datasets",
)
NON_NOTE_FILENAMES: frozenset[str] = frozenset({"README.md"})

CONFIG_PATH = ".labbrain/config.yaml"
ALLOWLIST_PATH = ".labbrain/phi-allow.yaml"
INDEX_FILE = "index.md"
LOG_DIR = "log"
RAW_DIR = "raw"

# phi-scan skips these directory names (and every dot-directory) at any depth,
# and these file names at the vault root only.
PHI_SKIP_DIR_NAMES: frozenset[str] = frozenset({"scratch", "__pycache__", "node_modules"})
PHI_SKIP_FILES: frozenset[str] = frozenset({INDEX_FILE})


def is_note_rel(rel: str) -> bool:
    """True if a vault-relative POSIX path is a note location."""
    path = PurePosixPath(rel)
    return (
        len(path.parts) >= 2
        and path.parts[0] in NOTE_FOLDERS
        and path.suffix == ".md"
        and path.name not in NON_NOTE_FILENAMES
    )


def iter_note_files(root: Path) -> Iterator[Path]:
    """Every candidate note file under the note folders, in a stable order."""
    for folder in NOTE_FOLDERS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.is_file() and path.name not in NON_NOTE_FILENAMES:
                yield path
