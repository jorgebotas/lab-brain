"""One finding type for lint, validate and phi-scan, plus renderers.

Every message passes through ``sanitize`` on construction. Rules are still
responsible for never putting field values or matched text into messages;
sanitize is the last line of defence (long digit runs and email-like tokens
are redacted, control characters stripped, length capped).
"""

from __future__ import annotations

import json
import re
from collections.abc import Container, Iterable, Mapping
from dataclasses import dataclass

from labbrain.ids import is_valid_id
from labbrain.layout import NOTE_TYPES

ERROR = "error"
WARNING = "warning"
INFO = "info"
_SEVERITIES = (ERROR, WARNING, INFO)
_SUMMARY_KEYS = {ERROR: "errors", WARNING: "warnings", INFO: "info"}
_GITHUB_LEVEL = {ERROR: "error", WARNING: "warning", INFO: "notice"}

# C0 and C1 controls, DEL, and the bidirectional formatting characters that can make a
# terminal show text in a different order from the bytes.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]+")
# Runs of six or more digits not inside a word. A run touching a hyphen or underscore
# is redacted too (a prefixed record number, say), unless it is exactly an ID's date
# stamp (eight digits reading as a 19xx/20xx calendar date, next to a hyphen).
_DIGIT_RUN = re.compile(r"(?<![^\W_])\d{6,}(?![^\W_])")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-])?(?:\(\d{3}\)\s?|\d{3}[.-])\d{3}[.-]\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")
_MAX_MESSAGE = 300
# Inputs longer than this are cut before the regexes run, which bounds their (backtracking)
# cost. The token straddling the cut is dropped whole, so no fragment of an identifier can
# escape redaction, however much whitespace collapsing later shrinks the text.
_PRE_CAP = 4 * _MAX_MESSAGE
_REDACTED = "[redacted]"

_ID_SHAPED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}\Z")
NOT_AN_ID = "<not a valid note ID>"
NOT_A_PATH = "<not a valid file path>"


def _is_id_date_stamp(text: str, start: int, end: int) -> bool:
    """True for an eight-digit run reading as YYYYMMDD (19xx/20xx) next to a hyphen."""
    if end - start != 8:
        return False
    if not ((start and text[start - 1] == "-") or (end < len(text) and text[end] == "-")):
        return False
    year, month, day = (
        int(text[start : start + 4]),
        int(text[start + 4 : start + 6]),
        int(text[start + 6 : end]),
    )
    return 1900 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31


def _redact_digit_run(match: re.Match[str]) -> str:
    if _is_id_date_stamp(match.string, match.start(), match.end()):
        return match.group(0)
    return _REDACTED


def _identifier_like(text: str) -> bool:
    """True if `text` holds anything sanitize would redact (SSN, phone, digit run, email)."""
    if _SSN.search(text) or _PHONE.search(text) or _EMAIL.search(text):
        return True
    return any(not _is_id_date_stamp(text, m.start(), m.end()) for m in _DIGIT_RUN.finditer(text))


def _valid_for_some_type(target: str, prefixes: Mapping[str, str] | None) -> bool:
    return any(is_valid_id(target, note_type, prefixes) for note_type in NOTE_TYPES)


def display_id(
    target: str,
    known: Container[str] | None = None,
    prefixes: Mapping[str, str] | None = None,
) -> str:
    """A link target or ID-bearing field value, safe to print.

    An existing note's ID is echoed. Any other value may be free text (a frontmatter
    value, a name, an identifier), so it is echoed only when it is a valid ID for one
    of the configured note types (`prefixes` overrides the default ID prefixes) and
    holds nothing identifier-like; otherwise it becomes a fixed placeholder.
    """
    if known is not None and target in known:
        return target
    if _valid_for_some_type(target, prefixes) and not _identifier_like(target):
        return target
    return NOT_AN_ID


def display_path(target: str) -> str:
    """A body link's file target, echoed only when path-shaped and nothing identifier-like."""
    if _ID_SHAPED.match(target) and not _identifier_like(target):
        return target
    return NOT_A_PATH


def strip_controls(text: str) -> str:
    """`text` with control and bidi-override characters replaced by spaces."""
    return _CONTROL.sub(" ", text)


def sanitize(message: str) -> str:
    """Strip control characters, redact identifier-like tokens, cap the length."""
    text = _CONTROL.sub(" ", message[:_PRE_CAP])
    if len(message) > _PRE_CAP:
        end = len(text)
        while end and not text[end - 1].isspace():
            end -= 1
        text = text[:end]
    text = _EMAIL.sub(_REDACTED, text)
    text = _SSN.sub(_REDACTED, text)
    text = _PHONE.sub(_REDACTED, text)
    text = _DIGIT_RUN.sub(_redact_digit_run, text)
    text = " ".join(text.split())
    if len(text) > _MAX_MESSAGE:
        text = text[: _MAX_MESSAGE - 1] + "…"
    return text


@dataclass(frozen=True)
class Finding:
    path: str  # vault-relative POSIX path; "" when not file-specific
    line: int  # 1-based; 0 when not line-specific
    rule: str
    severity: str
    message: str
    col: int = 0

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity}")
        object.__setattr__(self, "message", sanitize(self.message))

    def sort_key(self) -> tuple[str, int, int, str, str]:
        return (self.path, self.line, self.col, self.rule, self.message)

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "message": self.message,
        }


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    return sorted(findings, key=Finding.sort_key)


def summarize(findings: Iterable[Finding]) -> dict[str, int]:
    counts = {"errors": 0, "warnings": 0, "info": 0}
    for finding in findings:
        counts[_SUMMARY_KEYS[finding.severity]] += 1
    return counts


def exit_code(findings: Iterable[Finding]) -> int:
    return 1 if any(f.severity == ERROR for f in findings) else 0


def _render_text(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        loc = strip_controls(f.path) or "<vault>"
        if f.line:
            loc += f":{f.line}"
        if f.col:
            loc += f":{f.col}"
        lines.append(f"{loc}: {f.severity} [{strip_controls(f.rule)}] {f.message}")
    s = summarize(findings)
    lines.append(f"{s['errors']} error(s), {s['warnings']} warning(s), {s['info']} info")
    return "\n".join(lines)


def _render_json(findings: list[Finding]) -> str:
    return json.dumps(
        {"findings": [f.to_dict() for f in findings], "summary": summarize(findings)}, indent=2
    )


def _gh_escape(value: str) -> str:
    return strip_controls(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _gh_property(value: str) -> str:
    return _gh_escape(value).replace(":", "%3A").replace(",", "%2C")


def _render_github(findings: list[Finding]) -> str:
    out = []
    for f in findings:
        props = []
        if f.path:
            props.append(f"file={_gh_property(f.path)}")
        if f.line:
            props.append(f"line={f.line}")
        if f.col:
            props.append(f"col={f.col}")
        props.append(f"title={_gh_property(f.rule)}")
        out.append(f"::{_GITHUB_LEVEL[f.severity]} {','.join(props)}::{_gh_escape(f.message)}")
    return "\n".join(out)


_RENDERERS = {"text": _render_text, "json": _render_json, "github": _render_github}


def render(findings: Iterable[Finding], fmt: str) -> str:
    return _RENDERERS[fmt](list(findings))
