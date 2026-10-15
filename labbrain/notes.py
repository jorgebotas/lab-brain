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
import stat
import tempfile
import warnings
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError as RuamelYAMLError
from ruamel.yaml.scalarstring import SingleQuotedScalarString

from labbrain.schema import FUTURE_AGENTS_HEADING, ID_FIELDS, BaseNote, validate_frontmatter

_FM_RE = re.compile(r"\A---[ \t]*\r?\n(?P<fm>.*?)^---[ \t]*\r?$\n?", re.S | re.M)
_WIKILINK_RE = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_FILE_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}\Z")
H2_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*#*[ \t]*$")
HEADING_RE = re.compile(r"^#{1,6}[ \t]")

_SEQ_ITEM_RE = re.compile(r"^( *)-(?:[ \t]|$)")
_BLOCK_KEY_RE = re.compile(r"^( *)[^\s#-][^#]*:[ \t]*(?:#.*)?$")
_MERGE_TAG = "tag:yaml.org,2002:merge"

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class DuplicateKeyError(yaml.constructor.ConstructorError):
    """A mapping repeats a key. Carries only the position, never the key or value."""


class _StrictLoader(_LOADER):  # type: ignore[misc,valid-type]
    """The fast safe loader, but duplicate mapping keys are an error (as in ruamel)."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == _MERGE_TAG:
                continue
            key = self.construct_object(key_node, deep=True)
            try:
                duplicate = key in seen
            except TypeError:  # unhashable: the base constructor reports it
                continue
            if duplicate:
                raise DuplicateKeyError(problem="duplicate key", problem_mark=key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def safe_load(text: str) -> Any:
    """Fast, safe YAML read. Raises yaml.YAMLError on invalid input or duplicate keys."""
    return yaml.load(text, Loader=_StrictLoader)  # safe: subclass of (C)SafeLoader


_YAML11_RESOLVER = yaml.resolver.Resolver()
_STR_TAG = "tag:yaml.org,2002:str"


def _yaml11_safe(value: Any) -> Any:
    """`value` with every plain string PyYAML (YAML 1.1) would not read back as a string
    single-quoted, recursing into lists and mappings.

    ruamel writes YAML 1.2, where ``yes``, ``No``, ``on`` or ``12:30`` are plain strings,
    but reads go through PyYAML, which resolves them to booleans and numbers. Only values
    the tool writes pass through here; values loaded from a file and left unchanged are
    dumped as they were, so a frontmatter update never rewrites another field's line.
    Ruamel containers are updated in place so their flow style and comments survive.
    """
    if isinstance(value, str):
        if type(value) is str and (
            _YAML11_RESOLVER.resolve(yaml.ScalarNode, value, (True, False)) != _STR_TAG
        ):
            return SingleQuotedScalarString(value)
        return value
    if isinstance(value, CommentedSeq):
        for i, item in enumerate(value):
            value[i] = _yaml11_safe(item)
        return value
    if isinstance(value, CommentedMap):
        for key in list(value):
            value[key] = _yaml11_safe(value[key])
        return value
    if isinstance(value, list | tuple):
        return [_yaml11_safe(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _yaml11_safe(item) for key, item in value.items()}
    return value


def rt_yaml(*, seq_offset: int = 2) -> YAML:
    """Round-trip YAML configured for Obsidian's property style.

    ``seq_offset`` is how far block-sequence dashes sit right of their parent key:
    2 (Obsidian's style, dash indented under the key) or 0 (dash flush with the key).
    The setting is document-wide, so one note should use one style.
    """
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    if seq_offset == 0:
        yaml.indent(mapping=2, sequence=2, offset=0)
    else:
        yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _detect_seq_offset(frontmatter: str) -> int:
    """Dash offset of the first block-sequence item relative to its parent key; default 2."""
    parent: str | None = None
    for line in frontmatter.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = _SEQ_ITEM_RE.match(line)
        if item is not None and parent is not None:
            key = _BLOCK_KEY_RE.match(parent)
            if key is not None:
                return 0 if len(item.group(1)) == len(key.group(1)) else 2
        parent = line
    return 2


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
    # (body it was computed from, its fence-aware lines); see body_lines().
    _body_lines: tuple[str, list[tuple[int, str]]] | None = field(
        default=None, init=False, repr=False, compare=False
    )

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


def _yaml_error_line(exc: yaml.YAMLError | RuamelYAMLError) -> int:
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
        except DuplicateKeyError as exc:
            note.error_line = _yaml_error_line(exc)
            note.errors.append(f"frontmatter has a duplicate key (line {note.error_line})")
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
    """Parse a note file. An unreadable file becomes a Note with a read error, never a raise."""
    return parse_read_note(path, root, read_note_text(path))


def read_note_text(path: Path) -> str | None:
    """The file decoded as utf-8 with errors="replace", or None if it cannot be read.

    Safe to call from worker threads: it only reads.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_read_note(path: Path, root: Path, text: str | None) -> Note:
    """Parse what read_note_text returned; None becomes a Note with a read error."""
    rel = path.relative_to(root).as_posix()
    if text is None:
        return Note(
            path=path,
            rel=rel,
            text="",
            data=None,
            body="",
            body_line=1,
            errors=["cannot read file"],
        )
    return parse_note_text(text, path, rel)


def _scan_body_lines(body: str, body_line: int) -> list[tuple[int, str]]:
    """(file line number, line) for the lines of `body` outside fenced code blocks."""
    out: list[tuple[int, str]] = []
    in_fence = False
    for offset, line in enumerate(body.splitlines()):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((body_line + offset, line))
    return out


def body_lines(note: Note) -> list[tuple[int, str]]:
    """The fence-aware body lines, computed once per note body (do not mutate the list)."""
    cached = note._body_lines
    if cached is None or cached[0] is not note.body:
        cached = (note.body, _scan_body_lines(note.body, note.body_line))
        note._body_lines = cached
    return cached[1]


def iter_body_lines(note: Note) -> Iterator[tuple[int, str]]:
    """(file line number, line) for body lines outside fenced code blocks."""
    yield from body_lines(note)


def wikilink_targets(line: str) -> list[str]:
    # A link needs "[[" once inline code is removed; without a backtick nothing is removed,
    # and without any "[" removal cannot create one.
    if "[[" not in line and ("`" not in line or "[" not in line):
        return []
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
    for lineno, line in body_lines(note):
        refs.extend(LinkRef(target, lineno, "body") for target in wikilink_targets(line))
    return [ref for ref in refs if ref.target and ref.target != note.stem]


def h2_headings(note: Note) -> list[tuple[int, str]]:
    return [(n, m.group(1)) for n, line in body_lines(note) if (m := H2_RE.match(line))]


def future_agents_end(lines: Sequence[str]) -> int | None:
    """Index of the first line after the leading '## For future agents' block, else None.

    ``lines`` are the body lines from ``iter_body_lines``. The block runs from the
    heading (after any blank lines) to the next heading or the end of the body.
    """
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i == len(lines):
        return None
    match = H2_RE.match(lines[i])
    if match is None or match.group(1) != FUTURE_AGENTS_HEADING:
        return None
    i += 1
    while i < len(lines) and not HEADING_RE.match(lines[i]):
        i += 1
    return i


def future_agents_block(note: Note) -> list[str] | None:
    """Non-blank lines of the leading '## For future agents' block, else None."""
    lines = [line for _, line in body_lines(note)]
    end = future_agents_end(lines)
    if end is None:
        return None
    # lines[:end] is leading blanks, the heading, then the block.
    return [line for line in lines[:end] if line.strip()][1:]


def dump_frontmatter(data: Mapping[str, Any]) -> str:
    """YAML for tool-written frontmatter; YAML-1.1-ambiguous strings are quoted."""
    buffer = io.StringIO()
    rt_yaml().dump(_yaml11_safe(data), buffer)
    return buffer.getvalue()


def render_note(data: Mapping[str, Any], body: str) -> str:
    return f"---\n{dump_frontmatter(data)}---\n{body}"


def _target_mode(path: Path) -> int:
    """The existing file's permission bits, else what open() would create (0o666 & ~umask)."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def atomic_write(path: Path, text: str) -> None:
    """Write text verbatim (no newline translation) via a temp file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.chmod(tmp, _target_mode(path))  # mkstemp creates 0o600
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def update_frontmatter(path: Path, updates: Mapping[str, Any]) -> bool:
    """Set top-level frontmatter keys in place. Returns True if the file changed.

    Line endings, sequence indentation, key order, comments and quoting are kept, so
    changing one scalar touches only that key's lines (a block value spans several).
    Written strings that YAML 1.1 would not read as strings are single-quoted; values
    already in the file are written back unchanged. Errors name only the file and a line.
    """
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    match = _FM_RE.match(text)
    if match is None:
        raise ValueError(f"{path.name} has no frontmatter to update")
    crlf = text[: match.start("fm")].endswith("\r\n")
    frontmatter = match.group("fm").replace("\r\n", "\n")
    yaml = rt_yaml(seq_offset=_detect_seq_offset(frontmatter))
    # ruamel's warnings (a reused anchor, say) quote the YAML source, i.e. field values.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            data = yaml.load(frontmatter) or CommentedMap()
        except RuamelYAMLError as exc:
            line = _yaml_error_line(exc)
            message = f"{path.name}: frontmatter cannot be updated (line {line})"
            raise ValueError(message) from None
        changed = False
        for key, value in updates.items():
            if key in data and data[key] == value:
                continue
            data[key] = _yaml11_safe(value)
            changed = True
        if not changed:
            return False
        buffer = io.StringIO()
        yaml.dump(data, buffer)
    dumped = buffer.getvalue()
    if crlf:
        dumped = dumped.replace("\n", "\r\n")
    atomic_write(path, text[: match.start("fm")] + dumped + text[match.end("fm") :])
    return True
