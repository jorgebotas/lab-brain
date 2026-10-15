"""PHI scanner tests. Every identifier is synthetic and generated from a seeded RNG."""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, make_vault, write

from labbrain import lint
from labbrain.findings import render
from labbrain.phi import (
    AllowlistError,
    ScanSettings,
    iter_scan_files,
    line_hash,
    load_allowlist,
    scan,
    scan_text,
)
from labbrain.validate import validate_path
from labbrain.vault import Vault, load_config

RNG = random.Random(20261015)
TODAY = date(2026, 10, 15)


def mrn() -> str:
    return str(RNG.randrange(10_000_000, 99_999_999))


def phone() -> str:
    return f"{RNG.randrange(200, 999)}-555-{RNG.randrange(1000, 9999)}"


def ssn() -> str:
    return f"{RNG.randrange(100, 899)}-{RNG.randrange(10, 99)}-{RNG.randrange(1000, 9999)}"


def email() -> str:
    return f"user{RNG.randrange(1000, 9999)}@example.org"


def dob() -> str:
    return f"{RNG.randrange(1930, 2005)}-0{RNG.randrange(1, 9)}-1{RNG.randrange(0, 9)}"


def address() -> str:
    return f"{RNG.randrange(10, 9999)} Maple Grove Ave"


CASES: list[tuple[str, str, Callable[[], str]]] = [
    ("phi-mrn", "Patient MRN {} was excluded.", mrn),
    ("phi-date", "DOB: {}", dob),
    ("phi-phone", "Call {} for access.", phone),
    ("phi-email", "Contact {} about the cohort.", email),
    ("phi-ssn", "SSN {} on file.", ssn),
    ("phi-address", "Lives at {} near the clinic.", address),
]


@pytest.mark.parametrize(("rule", "template", "make"), CASES, ids=[c[0] for c in CASES])
def test_pattern_detected_with_position(rule: str, template: str, make: Callable[[], str]) -> None:
    value = make()
    line = template.format(value)
    hits = scan_text(f"intro\n{line}\n", ScanSettings())
    assert [(h.rule, h.line, h.col, h.length) for h in hits] == [
        (rule, 2, line.index(value) + 1, len(value))
    ]


@pytest.mark.parametrize(("rule", "template", "make"), CASES, ids=[c[0] for c in CASES])
def test_findings_never_echo_matched_text(
    tmp_path: Path, rule: str, template: str, make: Callable[[], str]
) -> None:
    value = make()
    root = make_vault(tmp_path)
    write(root, "concepts/leak.md", template.format(value) + "\n")
    findings = scan([root], root=root, settings=ScanSettings(), allow=frozenset())
    assert {f.rule for f in findings} == {rule}
    for fmt in ("text", "json", "github"):
        assert value not in render(findings, fmt)


def test_context_is_required() -> None:
    settings = ScanSettings()
    assert scan_text(f"Run {mrn()} finished in 2 hours.\n", settings) == []
    assert scan_text("Results as of 2026-10-15.\n", settings) == []
    assert scan_text("hidden sizes 128 256 1024\n", settings) == []
    assert scan_text("see arXiv 1512.00567\n", settings) == []


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("n = 5", True),
        ("N=5", True),
        ("n = 5 seeds", False),
        ("n = 3 folds", False),
        ("n = 5 samples", True),
        ("n = 12", False),
        ("n = 0", False),
        ("n <11", False),
        ("3 patients", True),
        ("count: 4", True),
        ("12 patients", False),
    ],
)
def test_inline_small_cells(text: str, flagged: bool) -> None:
    hits = scan_text(text + "\n", ScanSettings())
    assert bool(hits) is flagged
    assert all(h.rule == "phi-small-cell" for h in hits)


def test_overlapping_small_cell_patterns_report_once() -> None:
    assert len(scan_text("n = 4 patients\n", ScanSettings())) == 1


def test_table_small_cells_report_cell_column() -> None:
    text = "| group | n | seeds |\n|---|---|---|\n| a | 4 | 3 |\n| b | 40 | 2 |\n| c | <11 | 1 |\n"
    hits = scan_text(text, ScanSettings())
    assert [(h.rule, h.line, h.col) for h in hits] == [("phi-small-cell", 3, 7)]


def test_denylist_names(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, ".labbrain/phi-denylist.txt", "# synthetic\nZebulon Quixley\n")
    settings = ScanSettings.from_config(load_config(root), root)
    hits = scan_text("Seen by zebulon quixley today.\n", settings)
    assert [(h.rule, h.col, h.length) for h in hits] == [("phi-name", 9, 15)]


def test_custom_mrn_regex() -> None:
    settings = ScanSettings(mrn_regex=re.compile(r"\bID-(\d{5})\b"))
    hits = scan_text("ref ID-12345 ok\n", settings)
    assert [(h.rule, h.col, h.length) for h in hits] == [("phi-mrn", 8, 5)]


def test_allowlist_survives_line_shifts_and_expires_on_edit(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    line = f"Front desk {phone()} (synthetic)."
    path = write(root, "concepts/a.md", f"{line}\n")
    write(
        root,
        ".labbrain/phi-allow.yaml",
        f"- {{file: concepts/a.md, rule: phi-phone, line_sha256: '{line_hash(line)}', "
        "line_hint: 1, author: alice, date: 2026-10-15, reason: synthetic}\n",
    )
    allow = load_allowlist(root)

    def findings() -> list[str]:
        return [f.rule for f in scan([root], root=root, settings=ScanSettings(), allow=allow)]

    assert findings() == []
    path.write_text(f"new first line\n\n{line}\n")
    assert findings() == []
    path.write_text(f"{line} Edited.\n")
    assert findings() == ["phi-phone"]


@pytest.mark.parametrize("text", ["- {file: x}\n", "file: x\n", "- [unclosed\n"])
def test_invalid_allowlist(tmp_path: Path, text: str) -> None:
    root = make_vault(tmp_path)
    write(root, ".labbrain/phi-allow.yaml", text)
    with pytest.raises(AllowlistError):
        load_allowlist(root)


def test_scan_scope(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    for rel in [
        "concepts/a.md",
        "scratch/alice/b.md",
        ".obsidian/c.json",
        "index.md",
        "raw/papers/p.pdf",
        "log/2026-10-15.md",
        "manuscripts/main.md",
    ]:
        write(root, rel, "x\n")
    (root / "raw" / "bin.dat").write_bytes(b"\x00\x01")
    found = sorted(p.relative_to(root).as_posix() for p in iter_scan_files(root))
    assert found == ["concepts/a.md", "log/2026-10-15.md", "manuscripts/main.md"]


def test_phi_rule_respects_protected_flag(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "concepts/a.md", f"Call {phone()}.\n")
    assert [f.rule for f in lint.run(Vault.load(root), today=TODAY, only=["phi"])] == ["phi"]
    (root / ".labbrain" / "config.yaml").write_text(MIN_CONFIG + "protected_data: false\n")
    assert lint.run(Vault.load(root), today=TODAY, only=["phi"]) == []


def test_validate_scans_any_vault_file(vault_dir: Path) -> None:
    value = mrn()
    path = vault_dir / "manuscripts" / "main.md"
    path.parent.mkdir()
    path.write_text(f"Patient MRN {value}.\n")
    findings = validate_path(path)
    assert [(f.rule, f.message) for f in findings] == [("phi", "phi-mrn (span: 8 chars)")]
    assert value not in render(findings, "json")


def test_validation_errors_never_echo_identifiers(vault_dir: Path) -> None:
    value = mrn()
    bad_field = vault_dir / "concepts" / "bad.md"
    bad_field.write_text(
        "---\nid: bad\ntype: concept\ntitle: T\ncreated: 2026-10-01\nupdated: 2026-10-01\n"
        f"author: alice\nstatus: {value}\nsources: []\n---\n"
    )
    bad_yaml = vault_dir / "concepts" / "worse.md"
    bad_yaml.write_text(f"---\nid: worse\nnote: [{value}\n---\n")
    for path in (bad_field, bad_yaml):
        findings = validate_path(path)
        assert findings
        for fmt in ("text", "json", "github"):
            assert value not in render(findings, fmt)
