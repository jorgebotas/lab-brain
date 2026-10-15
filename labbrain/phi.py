"""PHI/PII scanner: context-aware identifier patterns plus small-cell counts.

Hits carry position and span length only, never text: an unmatched part of a
line may still hold an identifier the patterns missed, so no line content is
ever printed. Allowlist entries are keyed by a hash of the whole line, which
survives edits elsewhere in the file and is not practically reversible.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from labbrain.findings import ERROR, Finding, sort_findings
from labbrain.layout import ALLOWLIST_PATH, INDEX_FILE, PHI_SKIP_DIR_NAMES, PHI_SKIP_FILES
from labbrain.notes import safe_load
from labbrain.vault import Config, ConfigError

WINDOW = 30
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_HAS_DIGIT = re.compile(r"\d")
_DIGITS_6_12 = re.compile(r"(?<!\d)\d{6,12}(?!\d)")
_MRN_CONTEXT = re.compile(
    r"(?i)\b(?:mrn|medical\s+record|record\s*(?:no|number|#)|patient\s*id|chart)\b"
)
_DATE = re.compile(
    r"(?i)\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}-\d{1,2}-\d{4}"
    rf"|{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+{_MONTH}\s+\d{{4}})\b"
)
_DATE_CONTEXT = re.compile(
    r"(?i)\b(?:dob|d\.o\.b|born|birth\w*|admitted|admission|discharged?"
    r"|date\s+of\s+service|dos|visit\w*)\b"
)
_PHONE = re.compile(
    r"(?<!\w)(?:\+?1[\s.-])?(?:\(\d{3}\)\s?|\d{3}[.-])\d{3}[.-]\d{4}(?!\w)"
    r"|(?<!\w)\+[2-9]\d{0,2}(?:[\s.-]\d{1,4}){3,4}(?!\w)"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_SSN = re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])")
_ADDRESS = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][A-Za-z]+\.?\s+){1,4}"
    r"(?i:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct|way|place|pl"
    r"|terrace|ter|circle|cir|parkway|pkwy|highway|hwy)\b\.?"
)
_INLINE_N = re.compile(r"(?<!\w)[nN]\s*=\s*(\d{1,7})(?!\d)(?:\s+([A-Za-z][A-Za-z-]*))?")
_INLINE_COUNT = re.compile(r"(?i)\bcount\s*[:=]\s*(\d{1,7})(?!\d)")
_INLINE_PEOPLE = re.compile(
    r"(?i)(?<![\w.])(\d{1,7})\s+(?:patients|subjects|participants|individuals|cases|persons|people)\b"
)
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_CELL_COUNT = re.compile(r"\A(\d{1,7})(?:\s*\(.*\))?\Z")

PERSON_HEADERS = frozenset(
    {"n", "count", "patients", "subjects", "participants", "individuals", "cases"}
)
# Units after `n = k` that are not people. "samples" is deliberately absent: in
# clinical work it often means patients' samples.
ML_UNITS = frozenset(
    {
        "seed", "seeds", "run", "runs", "fold", "folds", "split", "splits", "epoch", "epochs",
        "layer", "layers", "head", "heads", "model", "models", "trial", "trials", "replicate",
        "replicates", "gpu", "gpus", "node", "nodes", "step", "steps", "batch", "batches",
        "token", "tokens", "class", "classes", "task", "tasks", "checkpoint", "checkpoints",
        "iteration", "iterations", "config", "configs", "sweep", "sweeps",
    }
)  # fmt: skip


@dataclass(frozen=True)
class PhiHit:
    rule: str
    line: int  # 1-based
    col: int  # 1-based
    length: int
    line_sha: str


def line_hash(line: str) -> str:
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:16]


def load_denylist(root: Path | None, rel_path: str) -> re.Pattern[str] | None:
    if root is None or not (root / rel_path).is_file():
        return None
    try:
        text = (root / rel_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # `from None`: a UnicodeDecodeError carries the raw bytes, i.e. the names.
        raise ConfigError("phi denylist file cannot be read") from None
    names = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not names:
        return None
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?i)(?<!\w)(?:{alternatives})(?!\w)")


@dataclass(frozen=True)
class ScanSettings:
    min_cell_size: int = 11
    mrn_regex: re.Pattern[str] | None = None
    denylist: re.Pattern[str] | None = None

    @classmethod
    def from_config(cls, config: Config, root: Path | None) -> ScanSettings:
        try:
            mrn = re.compile(config.phi.mrn_regex) if config.phi.mrn_regex else None
        except re.error as exc:
            raise ConfigError("phi.mrn_regex is not a valid regular expression") from exc
        return cls(config.min_cell_size, mrn, load_denylist(root, config.phi.denylist_file))


def _near(line: str, start: int, end: int, context: re.Pattern[str]) -> bool:
    before = line[max(0, start - WINDOW) : start]
    after = line[end : end + WINDOW]
    return context.search(before) is not None or context.search(after) is not None


def _inline_small_cells(line: str, min_cell: int) -> Iterator[tuple[str, int, int]]:
    for m in _INLINE_N.finditer(line):
        unit = (m.group(2) or "").lower()
        if 1 <= int(m.group(1)) < min_cell and unit not in ML_UNITS:
            yield "phi-small-cell", m.start(1), m.end(1)
    for pattern in (_INLINE_COUNT, _INLINE_PEOPLE):
        for m in pattern.finditer(line):
            if 1 <= int(m.group(1)) < min_cell:
                yield "phi-small-cell", m.start(1), m.end(1)


def _line_spans(line: str, settings: ScanSettings) -> Iterator[tuple[str, int, int]]:
    if "@" in line:
        for m in _EMAIL.finditer(line):
            yield "phi-email", m.start(), m.end()
    if settings.denylist is not None:
        for m in settings.denylist.finditer(line):
            yield "phi-name", m.start(), m.end()
    if not _HAS_DIGIT.search(line):
        return
    if settings.mrn_regex is not None:
        for m in settings.mrn_regex.finditer(line):
            group = 1 if m.re.groups else 0
            yield "phi-mrn", m.start(group), m.end(group)
    else:
        for m in _DIGITS_6_12.finditer(line):
            if _near(line, m.start(), m.end(), _MRN_CONTEXT):
                yield "phi-mrn", m.start(), m.end()
    for m in _DATE.finditer(line):
        if _near(line, m.start(), m.end(), _DATE_CONTEXT):
            yield "phi-date", m.start(), m.end()
    for rule_name, pattern in (("phi-phone", _PHONE), ("phi-ssn", _SSN), ("phi-address", _ADDRESS)):
        for m in pattern.finditer(line):
            yield rule_name, m.start(), m.end()
    yield from _inline_small_cells(line, settings.min_cell_size)


def _cells(line: str) -> list[tuple[int, str]]:
    """(0-based offset of the stripped cell text, cell text) for each table cell."""
    stripped = line.lstrip()
    offset = len(line) - len(stripped) + (1 if stripped.startswith("|") else 0)
    rest = line[offset:].rstrip()
    if rest.endswith("|"):
        rest = rest[:-1]
    cells, pos = [], offset
    for part in rest.split("|"):
        cells.append((pos + len(part) - len(part.lstrip()), part.strip()))
        pos += len(part) + 1
    return cells


def _table_small_cells(lines: list[str], min_cell: int) -> Iterator[tuple[int, int, int]]:
    i = 0
    while i < len(lines) - 1:
        if "|" not in lines[i] or not _TABLE_SEP.match(lines[i + 1]):
            i += 1
            continue
        headers = [text.strip("*_ ").lower() for _, text in _cells(lines[i])]
        columns = {k for k, header in enumerate(headers) if header in PERSON_HEADERS}
        j = i + 2
        while j < len(lines) and "|" in lines[j]:
            cells = _cells(lines[j]) if columns else []
            for k in sorted(columns):
                if k < len(cells):
                    start, text = cells[k]
                    m = _CELL_COUNT.match(text)
                    if m and 1 <= int(m.group(1)) < min_cell:
                        yield j + 1, start, start + len(m.group(1))
            j += 1
        i = j


def scan_text(text: str, settings: ScanSettings) -> list[PhiHit]:
    lines = text.splitlines()
    seen: set[tuple[str, int, int, int]] = set()
    hits: list[PhiHit] = []

    def add(rule_name: str, lineno: int, start: int, end: int) -> None:
        key = (rule_name, lineno, start, end)
        if key not in seen:
            seen.add(key)
            hits.append(
                PhiHit(rule_name, lineno, start + 1, end - start, line_hash(lines[lineno - 1]))
            )

    for lineno, line in enumerate(lines, start=1):
        for rule_name, start, end in _line_spans(line, settings):
            add(rule_name, lineno, start, end)
    for lineno, start, end in _table_small_cells(lines, settings.min_cell_size):
        add("phi-small-cell", lineno, start, end)
    return sorted(hits, key=lambda h: (h.line, h.col, h.rule))


_SNIFF_BYTES = 8192


def _is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def is_binary(path: Path) -> bool:
    if _is_pdf(path):
        return True
    with path.open("rb") as handle:
        return b"\0" in handle.read(_SNIFF_BYTES)


def _read_text(path: Path) -> str | None:
    """Decoded text, or None for a binary file. One open: the first 8 KB decide
    binary, and a binary file is never read past them. Raises OSError."""
    if _is_pdf(path):
        return None
    with path.open("rb") as handle:
        head = handle.read(_SNIFF_BYTES)
        if b"\0" in head:
            return None
        data = head + handle.read()
    return data.decode("utf-8", errors="replace")


def in_scan_scope(rel: str) -> bool:
    """False for paths phi-scan never reads: dot-directories, skip dirs, index.md."""
    parts = PurePosixPath(rel).parts
    if rel == INDEX_FILE:
        return False
    return not any(p.startswith(".") or p in PHI_SKIP_DIR_NAMES for p in parts[:-1])


def _iter_candidates(base: Path) -> Iterator[Path]:
    """Files in scope under `base`, unread. A directory that cannot be listed is
    yielded too, so the scan reports it instead of silently skipping it."""
    if base.is_file():
        yield base
        return
    unlisted: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(
        base, onerror=lambda e: unlisted.append(base if e.filename is None else Path(e.filename))
    ):
        yield from unlisted
        unlisted.clear()
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in PHI_SKIP_DIR_NAMES
        )
        here = Path(dirpath)
        for name in sorted(filenames):
            if here == base and name in PHI_SKIP_FILES:
                continue
            path = here / name
            if path.is_file():
                yield path
    yield from unlisted


def iter_scan_files(base: Path) -> Iterator[Path]:
    """Text files phi-scan reads under `base`. Unreadable entries are kept (fail closed)."""
    for path in _iter_candidates(base):
        try:
            if is_binary(path):
                continue
        except OSError:
            pass
        yield path


class AllowlistError(ConfigError):
    """The PHI allowlist file is malformed."""


_ALLOW_KEYS = ("file", "rule", "line_sha256", "author", "date")


def load_allowlist(root: Path | None) -> frozenset[tuple[str, str, str]]:
    if root is None or not (root / ALLOWLIST_PATH).is_file():
        return frozenset()
    try:
        raw = safe_load((root / ALLOWLIST_PATH).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AllowlistError(f"{ALLOWLIST_PATH} is not valid YAML") from exc
    raw = [] if raw is None else raw
    if not isinstance(raw, list):
        raise AllowlistError(f"{ALLOWLIST_PATH} must be a YAML list")
    entries = set()
    for number, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict) or any(not entry.get(k) for k in _ALLOW_KEYS):
            raise AllowlistError(f"{ALLOWLIST_PATH} entry {number} needs {', '.join(_ALLOW_KEYS)}")
        entries.add((str(entry["file"]), str(entry["rule"]), str(entry["line_sha256"])[:16]))
    return frozenset(entries)


def _rel(path: Path, root: Path | None) -> str:
    """`path` relative to `root`; both must already be resolved."""
    if root is not None:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            pass
    return path.as_posix()


UNREADABLE_RULE = "phi-unreadable"


def scan(
    paths: Iterable[Path],
    *,
    root: Path | None,
    settings: ScanSettings,
    allow: frozenset[tuple[str, str, str]],
    rule_name: str | None = None,
) -> list[Finding]:
    findings = []
    resolved_root = root.resolve() if root is not None else None
    for base in paths:
        # Without a root, paths are reported as given (e.g. relative to the cwd).
        start = base.resolve() if resolved_root is not None else base
        for path in _iter_candidates(start):
            rel = _rel(path, resolved_root)
            try:
                text = _read_text(path)
            except OSError:
                findings.append(
                    Finding(
                        rel, 0, rule_name or UNREADABLE_RULE, ERROR, "file could not be scanned"
                    )
                )
                continue
            if text is None:
                continue
            for hit in scan_text(text, settings):
                if (rel, hit.rule, hit.line_sha) in allow:
                    continue
                span = f"(span: {hit.length} chars)"
                message = span if rule_name is None else f"{hit.rule} {span}"
                findings.append(
                    Finding(rel, hit.line, rule_name or hit.rule, ERROR, message, col=hit.col)
                )
    return sort_findings(findings)
