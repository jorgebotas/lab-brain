"""Vault discovery, configuration, time, and the load-once note graph."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from labbrain import __version__
from labbrain.ids import DEFAULT_PREFIXES
from labbrain.layout import CONFIG_PATH, iter_note_files
from labbrain.notes import Note, parse_note, safe_load

ENV_VAULT = "LABBRAIN_VAULT"
ENV_NOW = "LABBRAIN_NOW"


class VaultNotFound(Exception):
    """No vault could be located."""


class ConfigError(Exception):
    """The vault configuration (or an environment override) is invalid."""


def now() -> datetime:
    raw = os.environ.get(ENV_NOW)
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ConfigError(f"{ENV_NOW} is not an ISO datetime") from exc
    return datetime.now()


def today() -> date:
    return now().date()


def _checked_root(path: Path, source: str) -> Path:
    root = path.expanduser().resolve()
    if not (root / CONFIG_PATH).is_file():
        raise VaultNotFound(f"{source} points to {root}, which has no {CONFIG_PATH}")
    return root


def find_root(start: Path | None = None, explicit: Path | str | None = None) -> Path:
    """--vault, else LABBRAIN_VAULT, else the nearest ancestor with .labbrain/config.yaml."""
    if explicit:
        return _checked_root(Path(explicit), "--vault")
    env = os.environ.get(ENV_VAULT)
    if env:
        return _checked_root(Path(env), ENV_VAULT)
    here = (start or Path.cwd()).expanduser().resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_PATH).is_file():
            return candidate
    raise VaultNotFound(
        f"no vault found: pass --vault, set {ENV_VAULT}, "
        f"or run inside a directory containing {CONFIG_PATH}"
    )


DEFAULT_HASH_IGNORE: list[str] = [
    "seed",
    "*.seed",
    "output_dir",
    "*.output_dir",
    "timestamp",
    "*.timestamp",
    "run_name",
    "*.run_name",
]


class TrackerConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    backend: str = "local"
    project: str | None = None
    runs_dir: str = "runs"


class PhiConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    mrn_regex: str | None = None
    denylist_file: str = ".labbrain/phi-denylist.txt"


class Config(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_name: str
    project_slug: str
    owner: str = ""
    lab_members: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=lambda: ["claude", "codex", "gemini"])
    modality: str = "other"
    tracker: TrackerConfig = Field(default_factory=TrackerConfig)
    protected_data: bool = True
    data_paths: list[str] = Field(default_factory=list)
    min_cell_size: int = Field(default=11, ge=2)
    code_repo: str = ""
    vault_location: Literal["standalone", "subfolder"] = "standalone"
    target_venues: list[str] = Field(default_factory=list)
    engine_min_version: str = "0.1.0"
    id_prefixes: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_PREFIXES))
    inbox_max_days: int = Field(default=30, ge=1)
    headline_metrics: list[str] = Field(default_factory=list)
    hash_ignore: list[str] = Field(default_factory=lambda: list(DEFAULT_HASH_IGNORE))
    protocol_key: str = "eval.protocol"
    search: Literal["none", "qmd"] = "none"
    phi: PhiConfig = Field(default_factory=PhiConfig)

    @field_validator("id_prefixes")
    @classmethod
    def _merge_prefixes(cls, value: dict[str, str]) -> dict[str, str]:
        return {**DEFAULT_PREFIXES, **value}

    def is_agent(self, author: str | None) -> bool:
        return bool(author) and author in self.agents

    def author_allowed(self, author: str | None) -> bool:
        if not author:
            return False
        return not self.lab_members or author in self.lab_members or author in self.agents


_CONFIG_FIELDS: frozenset[str] = frozenset(
    {*Config.model_fields, *TrackerConfig.model_fields, *PhiConfig.model_fields}
)


def _render_config_loc(loc: tuple[int | str, ...]) -> str:
    """Render an error location without echoing config content: dict keys become `<key>`."""
    parts: list[str] = []
    for index, part in enumerate(loc):
        next_part = loc[index + 1] if index + 1 < len(loc) else None
        if isinstance(part, str) and part in _CONFIG_FIELDS:
            parts.append(part)
        elif (
            isinstance(part, int) and not isinstance(part, bool) and index and next_part != "[key]"
        ):
            parts.append(str(part))  # list index (the top level is always a mapping)
        elif part == "[key]":
            continue  # marker after a dict key whose own type is wrong
        else:
            parts.append("<key>")
    return ".".join(parts) or "config"


def default_config() -> Config:
    """Settings for running outside any vault (e.g. phi-scan over a code repo)."""
    return Config(project_name="(no vault)", project_slug="none")


def load_config(root: Path) -> Config:
    try:
        raw: Any = safe_load((root / CONFIG_PATH).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {CONFIG_PATH}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{CONFIG_PATH} is not valid UTF-8") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{CONFIG_PATH} is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{CONFIG_PATH} must be a YAML mapping")
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{_render_config_loc(e['loc'])}: {e['msg']}"
            for e in exc.errors(include_url=False, include_context=False, include_input=False)
        )
        raise ConfigError(f"{CONFIG_PATH}: {details}") from exc


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])


def version_warning(config: Config) -> str | None:
    if _version_tuple(__version__) < _version_tuple(config.engine_min_version):
        return (
            f"labbrain {__version__} is older than this vault's engine_min_version "
            f"{config.engine_min_version}; update the lab-brain plugin"
        )
    return None


@dataclass
class Vault:
    root: Path
    config: Config
    notes: dict[str, Note]
    duplicates: dict[str, list[Note]]
    by_rel: dict[str, Note]
    inbound: dict[str, set[str]]
    outbound: dict[str, set[str]]

    @classmethod
    def load(cls, root: Path, config: Config | None = None) -> Vault:
        root = root.resolve()
        config = config or load_config(root)
        groups: dict[str, list[Note]] = defaultdict(list)
        by_rel: dict[str, Note] = {}
        for path in iter_note_files(root):
            note = parse_note(path, root)
            groups[note.stem].append(note)
            by_rel[note.rel] = note
        inbound: dict[str, set[str]] = defaultdict(set)
        outbound: dict[str, set[str]] = defaultdict(set)
        for note in by_rel.values():
            for ref in note.refs:
                if not ref.is_path:
                    outbound[note.stem].add(ref.target)
                    inbound[ref.target].add(note.stem)
        return cls(
            root=root,
            config=config,
            notes={stem: group[0] for stem, group in groups.items()},
            duplicates={stem: group for stem, group in groups.items() if len(group) > 1},
            by_rel=by_rel,
            inbound=dict(inbound),
            outbound=dict(outbound),
        )

    def get(self, note_id: str) -> Note | None:
        return self.notes.get(note_id)

    def all_notes(self) -> list[Note]:
        """Every parsed note file, duplicates included."""
        return list(self.by_rel.values())

    def of_type(self, note_type: str) -> list[Note]:
        return [note for note in self.notes.values() if note.type == note_type]
