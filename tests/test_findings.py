from __future__ import annotations

import json
import random
import time

import pytest

from labbrain.findings import (
    ERROR,
    INFO,
    NOT_A_PATH,
    NOT_AN_ID,
    WARNING,
    Finding,
    display_id,
    display_path,
    exit_code,
    render,
    sanitize,
    set_id_prefixes,
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


@pytest.mark.parametrize(
    ("message", "expected_len"),
    [
        ("a" * 100_000, 0),  # one token cut by the pre-cap: dropped whole
        ("a" * 1_199 + " " + "a" * 98_800, 300),  # longest surviving run: worst-case regex work
    ],
    ids=["single-token", "surviving-run"],
)
def test_sanitize_long_input_is_fast(message: str, expected_len: int) -> None:
    start = time.perf_counter()
    msg = sanitize(message)
    assert time.perf_counter() - start < 0.1
    assert len(msg) == expected_len


@pytest.mark.parametrize(
    ("padding", "value"),
    [
        (" " * 1195, "1234567890"),
        (" " * 1190, "someone@example.org"),
        ("\x00" * 1195, "1234567890"),  # control chars become whitespace after the cut
    ],
    ids=["digits", "email", "digits-after-control-chars"],
)
def test_sanitize_pre_cap_drops_cut_token(padding: str, value: str) -> None:
    msg = sanitize(padding + value)
    for end in range(5, len(value) + 1):
        assert value[:end] not in msg


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


def _synthetic_identifiers(seed: int) -> dict[str, str]:
    """PHI-shaped strings that are also syntactically ID- or path-shaped."""
    rng = random.Random(seed)
    d = lambda n: "".join(str(rng.randrange(10)) for _ in range(n))  # noqa: E731
    return {
        "ssn": f"{rng.randrange(100, 899)}-{d(2)}-{d(4)}",
        "phone": f"{rng.randrange(200, 999)}-{rng.randrange(200, 999)}-{d(4)}",
        "phone-dots": f"{rng.randrange(200, 999)}.{rng.randrange(200, 999)}.{d(4)}",
        "mrn-prefixed": f"MRN-00{d(6)}",
        "mrn-lower": f"mrn-00{d(6)}",
        "mrn-underscore": f"mrn_00{d(6)}",
        "slug-digits": f"case-{d(9)}",
    }


@pytest.mark.parametrize("kind", sorted(_synthetic_identifiers(5)))
def test_sanitize_redacts_hyphen_adjacent_identifiers(kind: str) -> None:
    value = _synthetic_identifiers(5)[kind]
    msg = sanitize(f"unresolved link [[{value}]] and {value}")
    digits = "".join(ch for ch in value if ch.isdigit())
    assert value not in msg
    assert digits[-6:] not in msg.replace("-", "").replace(".", "")


def test_sanitize_keeps_dated_ids() -> None:
    text = "see EXP-20261013-a, HO-20261014-1420-claude, CLM-20261001-b-2 and DS-19991231-x"
    assert sanitize(text) == text


@pytest.mark.parametrize("kind", sorted(_synthetic_identifiers(9)))
def test_display_id_hides_identifier_shaped_targets(kind: str) -> None:
    value = _synthetic_identifiers(9)[kind]
    assert display_id(value) == NOT_AN_ID
    assert display_id(f"EXP-20261001-{value.lower()}") == NOT_AN_ID


def test_display_id_echoes_valid_ids_and_known_notes() -> None:
    for valid in (
        "EXP-20261001-baseline",
        "EVAL-v2",
        "EVAL-v3-holdout",
        "LIT-szegedy2016-rethinking",
        "HO-20261014-1420-claude",
        "label-smoothing",
    ):
        assert display_id(valid) == valid
    for invalid in ("figures/roc.png", "Jane Doe", "EXP-1", "notes.md", "X-20261001-a"):
        assert display_id(invalid) == NOT_AN_ID
    assert display_id("Odd Name", known={"Odd Name"}) == "Odd Name"
    assert display_id("RUN-20261001-a", prefixes={"experiment": "RUN"}) == "RUN-20261001-a"
    assert display_id("EXP-20261001-a", prefixes={"experiment": "RUN"}) == NOT_AN_ID


def test_sanitize_strips_c1_controls_and_bidi_overrides() -> None:
    msg = sanitize("a\x9b31mb \u202eevil\u202c c\u2066d\u2069")
    assert not any(ch in msg for ch in "\x9b\u202e\u202c\u2066\u2069")


def test_renderers_strip_controls_from_path_and_rule() -> None:
    finding = Finding("dir/a\x1b[31m\u202e.md", 2, "ru\nle", ERROR, "m")
    for fmt in ("text", "github"):
        out = render([finding], fmt)
        assert not any(ch in out for ch in "\x1b\u202e"), fmt
        assert "ru\nle" not in out, fmt


def test_display_id_hides_letter_adjacent_digit_runs() -> None:
    """A concept slug may glue a long number to letters; display_id still hides it."""
    rng = random.Random(43)
    for value in (f"mrn{rng.randrange(10**7, 10**8)}", f"case-x{rng.randrange(10**6, 10**7)}"):
        assert display_id(value) == NOT_AN_ID
    assert display_id("resnet152-gpt4") == "resnet152-gpt4"


def _birth_date(seed: int) -> str:
    """A synthetic YYYYMMDD that reads as a 20th-century calendar date."""
    rng = random.Random(seed)
    return f"19{rng.randrange(40, 99)}{rng.randrange(1, 12):02d}{rng.randrange(1, 28):02d}"


def test_sanitize_redacts_date_shaped_runs_outside_the_id_stamp() -> None:
    """Only the stamp right after an ID prefix is kept: a date glued to a name, or one
    later in an ID's slug, can be a date of birth."""
    born = _birth_date(46)
    for text in (
        f"patient-{born}",
        f"{born}-visit",
        f"jane-doe-{born}-x",
        f"EXP-20261001-born-{born}",
        f"EXP-{born}",
        f"exp-{born}-a",
    ):
        assert born not in sanitize(f"see {text} now"), text


def test_sanitize_keeps_stamps_in_id_position() -> None:
    text = "[[HO-20261014-1420-x]] in experiments/EXP-20261001-a.md (DS-20261001-a)"
    assert sanitize(text) == text


def test_stamp_is_exempt_only_after_a_dated_id_prefix() -> None:
    """An upper-case token is not enough: MRN-, DOB- or an initial can front a birth date."""
    born = _birth_date(48)
    for text in (
        f"MRN-{born}-x",
        f"J-{born}-x",
        f"DOB-{born}-x",
        f"LIT-{born}-x",
        f"a_EXP-{born}-x",
    ):
        assert born not in sanitize(f"see {text}"), text
    assert display_path(f"people/J-{born}-smith.md") == NOT_A_PATH


def test_configured_prefixes_keep_their_stamps() -> None:
    set_id_prefixes({"experiment": "LAB-EXP", "claim": "Clm", "dataset": "A" * 20})
    text = f"LAB-EXP-20261001-a, Clm-20261001-b and {'A' * 20}-20261001-c"
    assert sanitize(text) == text
    assert "20261001" not in sanitize("EXP-20261001-a")  # not an ID prefix in this vault
    set_id_prefixes({"experiment": ""})  # an empty prefix must not spare every stamp
    assert "19800412" not in sanitize("see -19800412-a")
    set_id_prefixes(None)
    assert sanitize("EXP-20261001-a") == "EXP-20261001-a"


def test_display_hides_date_shaped_slugs() -> None:
    born = _birth_date(47)
    assert display_id(f"jane-{born}-x") == NOT_AN_ID  # a syntactically valid concept slug
    assert display_id(f"EXP-20261001-born-{born}") == NOT_AN_ID
    assert display_path(f"people/jane-{born}.md") == NOT_A_PATH
    assert display_path("experiments/EXP-20261001-a.md") == "experiments/EXP-20261001-a.md"
