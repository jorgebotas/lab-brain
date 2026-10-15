from __future__ import annotations

import json
import time

import pytest

from labbrain.findings import (
    ERROR,
    INFO,
    WARNING,
    Finding,
    exit_code,
    render,
    sanitize,
    sort_findings,
    summarize,
)


def test_sanitize_redacts_long_digit_runs_and_emails() -> None:
    msg = sanitize("patient 12345678 wrote to someone@example.org")
    assert "12345678" not in msg
    assert "someone@example.org" not in msg
    assert msg.count("[redacted]") == 2


def test_sanitize_keeps_ids_and_short_numbers() -> None:
    text = "unresolved link [[EXP-20261013-label-smoothing]] line 42"
    assert sanitize(text) == text


def test_sanitize_strips_control_chars_and_caps_length() -> None:
    msg = sanitize("a\nb\x1b[31m" + "x" * 500)
    assert "\n" not in msg and "\x1b" not in msg
    assert len(msg) == 300


def test_sanitize_long_input_is_fast() -> None:
    start = time.perf_counter()
    msg = sanitize("a" * 100_000)
    assert time.perf_counter() - start < 0.1
    assert len(msg) == 300


def test_finding_sanitizes_on_construction() -> None:
    finding = Finding("a.md", 1, "schema", ERROR, "value 987654321 bad")
    assert "987654321" not in finding.message


def test_unknown_severity_rejected() -> None:
    with pytest.raises(ValueError):
        Finding("a.md", 1, "x", "fatal", "m")


def test_summary_and_exit_code() -> None:
    findings = [
        Finding("a.md", 1, "r", ERROR, "m"),
        Finding("b.md", 2, "r", WARNING, "m"),
        Finding("", 0, "r", INFO, "m"),
    ]
    assert summarize(findings) == {"errors": 1, "warnings": 1, "info": 1}
    assert exit_code(findings) == 1
    assert exit_code(findings[1:]) == 0


def test_sort_is_deterministic() -> None:
    a = Finding("b.md", 1, "r", ERROR, "m")
    b = Finding("a.md", 9, "r", ERROR, "m")
    c = Finding("a.md", 2, "r", ERROR, "m")
    assert sort_findings([a, b, c]) == [c, b, a]


def test_render_json_shape() -> None:
    out = render([Finding("a.md", 3, "orphan", WARNING, "no inbound links", col=2)], "json")
    assert json.loads(out) == {
        "findings": [
            {
                "rule": "orphan",
                "severity": "warning",
                "path": "a.md",
                "line": 3,
                "col": 2,
                "message": "no inbound links",
            }
        ],
        "summary": {"errors": 0, "warnings": 1, "info": 0},
    }


def test_render_text() -> None:
    out = render([Finding("a.md", 3, "orphan", WARNING, "no inbound links")], "text")
    assert out.splitlines() == [
        "a.md:3: warning [orphan] no inbound links",
        "0 error(s), 1 warning(s), 0 info",
    ]


def test_render_github_escapes() -> None:
    out = render([Finding("dir/a,b.md", 3, "schema", ERROR, "50% bad\nx")], "github")
    assert out == "::error file=dir/a%2Cb.md,line=3,title=schema::50%25 bad x"


def test_render_github_empty_is_empty() -> None:
    assert render([], "github") == ""
