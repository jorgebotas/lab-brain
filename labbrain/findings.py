"""One finding type for lint, validate and phi-scan, plus renderers.

Every message passes through ``sanitize`` on construction. Rules are still
responsible for never putting field values or matched text into messages;
sanitize is the last line of defence (long digit runs and email-like tokens
are redacted, control characters stripped, length capped).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

ERROR = "error"
WARNING = "warning"
INFO = "info"
_SEVERITIES = (ERROR, WARNING, INFO)
_SUMMARY_KEYS = {ERROR: "errors", WARNING: "warnings", INFO: "info"}
_GITHUB_LEVEL = {ERROR: "error", WARNING: "warning", INFO: "notice"}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_DIGIT_RUN = re.compile(r"(?<![\w-])\d{6,}(?![\w-])")
_EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")
_MAX_MESSAGE = 300
# Inputs longer than this are cut before the regexes run, which bounds their (backtracking)
# cost. The token straddling the cut is dropped whole, so no fragment of an identifier can
# escape redaction, however much whitespace collapsing later shrinks the text.
_PRE_CAP = 4 * _MAX_MESSAGE


def sanitize(message: str) -> str:
    """Strip control characters, redact identifier-like tokens, cap the length."""
    text = _CONTROL.sub(" ", message[:_PRE_CAP])
    if len(message) > _PRE_CAP:
        end = len(text)
        while end and not text[end - 1].isspace():
            end -= 1
        text = text[:end]
    text = _EMAIL.sub("[redacted]", text)
    text = _DIGIT_RUN.sub("[redacted]", text)
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
        loc = f.path or "<vault>"
        if f.line:
            loc += f":{f.line}"
        if f.col:
            loc += f":{f.col}"
        lines.append(f"{loc}: {f.severity} [{f.rule}] {f.message}")
    s = summarize(findings)
    lines.append(f"{s['errors']} error(s), {s['warnings']} warning(s), {s['info']} info")
    return "\n".join(lines)


def _render_json(findings: list[Finding]) -> str:
    return json.dumps(
        {"findings": [f.to_dict() for f in findings], "summary": summarize(findings)}, indent=2
    )


def _gh_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


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
