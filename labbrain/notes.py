"""Markdown notes: frontmatter split, YAML read and write, links and sections.

Reads use PyYAML's libyaml-backed safe loader: ruamel's loader is pure Python
since 0.19 and is too slow for the 3 s lint budget. Writes re-load the
frontmatter with ruamel in round-trip mode so key order, comments and quoting
survive and a one-field change is a one-line diff. Error messages never quote
YAML input.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from labbrain.schema import FUTURE_AGENTS_HEADING, ID_FIELDS, BaseNote, validate_frontmatter

_FM_RE = re.compile(r"\A---[ \t]*\r?\n(?P<fm>.*?)^---[ \t]*\r?$\n?", re.S | re.M)
_WIKILINK_RE = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_FILE_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}\Z")
H2_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*#*[ \t]*$")
HEADING_RE = re.compile(r"^#{1,6}[ \t]")

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def safe_load(text: str) -> Any:
    """Fast, safe YAML read. Raises yaml.YAMLError on invalid input."""
    return yaml.load(text, Loader=_LOADER)  # safe: only SafeLoader or CSafeLoader


def rt_yaml() -> YAML:
    """Round-trip YAML configured for Obsidian's property style."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


@dataclass(frozen=True)
class LinkRef:
    target: str
    line: int  # 1-based line in the file; frontmatter links report line 1
    field: str  # frontmatter field name, or "body"

    @property
    def is_path(self) -> bool:
        """Vault-relative file targets (figures, PDFs) rather than note IDs."""
        return "/" in self.target or bool(_FILE_EXT_RE.search(self.target))


@dataclass
class Note:
    path: Path
    rel: str
    text: str
    data: dict[str, Any] | None
    body: str
    body_line: int
    model: BaseNote | None = None
    errors: list[str] = field(default_factory=list)
    error_line: int = 1
    refs: list[LinkRef] = field(default_factory=list)

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def type(self) -> str | None:
        value = self.data.get("type") if self.data else None
        return value if isinstance(value, str) else None

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default) if self.data else default

    def get_str(self, key: str) -> str | None:
        value = self.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    def get_list(self, key: str) -> list[str]:
        value = self.get(key)
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        return []

    def get_date(self, key: str) -> date | None:
        value = self.get(key)
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None


def split_frontmatter(text: str) -> tuple[str | None, str, int]:
    """Return (frontmatter text or None, body, 1-based line where the body starts)."""
    match = _FM_RE.match(text)
    if match is None:
        return None, text, 1
    return match.group("fm"), text[match.end() :], match.group(0).count("\n") + 1


def _yaml_error_line(exc: yaml.YAMLError) -> int:
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    return mark.line + 2 if mark is not None else 1  # +1 one-based, +1 opening ---


def parse_note_text(text: str, path: Path, rel: str) -> Note:
    fm, body, body_line = split_frontmatter(text)
    note = Note(path=path, rel=rel, text=text, data=None, body=body, body_line=body_line)
    if fm is None:
        note.errors.append("missing YAML frontmatter")
    else:
        try:
            loaded = safe_load(fm)
        except yaml.YAMLError as exc:
            note.error_line = _yaml_error_line(exc)
            note.errors.append(f"frontmatter is not valid YAML (line {note.error_line})")
        else:
            loaded = {} if loaded is None else loaded
            if isinstance(loaded, dict):
                note.data = loaded
                note.model, errors = validate_frontmatter(loaded)
                note.errors.extend(errors)
            else:
                note.errors.append("frontmatter must be a YAML mapping")
    note.refs = _harvest_links(note)
    return note


def parse_note(path: Path, root: Path) -> Note:
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_note_text(text, path, path.relative_to(root).as_posix())


def iter_body_lines(note: Note) -> Iterator[tuple[int, str]]:
    """(file line number, line) for body lines outside fenced code blocks."""
    in_fence = False
    for offset, line in enumerate(note.body.splitlines()):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield note.body_line + offset, line


def wikilink_targets(line: str) -> list[str]:
    targets = []
    for match in _WIKILINK_RE.finditer(_INLINE_CODE_RE.sub("", line)):
        raw = match.group(1).split("\\|", 1)[0].split("|", 1)[0]
        target = re.split(r"[#^]", raw, maxsplit=1)[0].strip()
        if target:
            targets.append(target)
    return targets


def _harvest_links(note: Note) -> list[LinkRef]:
    refs: list[LinkRef] = []
    if note.data:
        for name in ID_FIELDS:
            refs.extend(LinkRef(target.strip(), 1, name) for target in note.get_list(name))
    for lineno, line in iter_body_lines(note):
        refs.extend(LinkRef(target, lineno, "body") for target in wikilink_targets(line))
    return [ref for ref in refs if ref.target and ref.target != note.stem]


def h2_headings(note: Note) -> list[tuple[int, str]]:
    return [(n, m.group(1)) for n, line in iter_body_lines(note) if (m := H2_RE.match(line))]


def future_agents_block(note: Note) -> list[str] | None:
    """Non-blank lines of the leading '## For future agents' block, else None."""
    lines = [line for _, line in iter_body_lines(note)]
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i == len(lines):
        return None
    match = H2_RE.match(lines[i])
    if match is None or match.group(1) != FUTURE_AGENTS_HEADING:
        return None
    block = []
    for line in lines[i + 1 :]:
        if HEADING_RE.match(line):
            break
        if line.strip():
            block.append(line)
    return block


def dump_frontmatter(data: Mapping[str, Any]) -> str:
    buffer = io.StringIO()
    rt_yaml().dump(data, buffer)
    return buffer.getvalue()


def render_note(data: Mapping[str, Any], body: str) -> str:
    return f"---\n{dump_frontmatter(data)}---\n{body}"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def update_frontmatter(path: Path, updates: Mapping[str, Any]) -> bool:
    """Set top-level frontmatter keys in place. Returns True if the file changed."""
    text = path.read_text(encoding="utf-8")
    match = _FM_RE.match(text)
    if match is None:
        raise ValueError(f"{path.name} has no frontmatter to update")
    yaml = rt_yaml()
    data = yaml.load(match.group("fm")) or CommentedMap()
    changed = False
    for key, value in updates.items():
        if key in data and data[key] == value:
            continue
        data[key] = value
        changed = True
    if not changed:
        return False
    buffer = io.StringIO()
    yaml.dump(data, buffer)
    atomic_write(path, text[: match.start("fm")] + buffer.getvalue() + text[match.end("fm") :])
    return True
