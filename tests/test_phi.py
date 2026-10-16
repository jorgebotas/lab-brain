"""PHI scanner tests. Every identifier is synthetic and generated from a seeded RNG."""

from __future__ import annotations

import os
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
from labbrain.vault import ConfigError, Vault, load_config

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
        ("Excluded: n = 4.", True),
        ("n = 1,000 cells", False),
        ("N = 2,500", False),
        ("n = 4.5", False),
        ("2,005 patients", False),
        ("count: 3,200", False),
        ("1.5 patients", False),
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


@pytest.mark.parametrize(
    "header",
    [
        "n (%)",
        "N (%)",
        "n(%)",
        "No. of patients",
        "no of subjects",
        "Number of participants",
        "n patients",
        "Patients, n (%)",
        "patients (%)",
        "**Cases**",
    ],
)
def test_table_person_count_headers(header: str) -> None:
    text = f"| arm | {header} |\n|---|---|\n| a | 4 (12%) |\n| b | 40 (88%) |\n"
    hits = scan_text(text, ScanSettings())
    assert [(h.rule, h.line, h.col) for h in hits] == [("phi-small-cell", 3, 7)]


@pytest.mark.parametrize("header", ["No.", "Number", "seed (%)", "accuracy (%)", "n layers"])
def test_table_headers_that_are_not_person_counts(header: str) -> None:
    text = f"| arm | {header} |\n|---|---|\n| a | 4 |\n"
    assert scan_text(text, ScanSettings()) == []


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


def test_lines_are_scanned_independently() -> None:
    """Matching is per line: no match spans a line break."""
    settings = ScanSettings()
    assert scan_text("Lives at 12\nMaple Grove Ave today.\n", settings) == []
    assert scan_text("Patient MRN\n" + mrn() + " later.\n", settings) == []
    assert scan_text("n =\n4 patients\n", settings) != []  # "4 patients" alone is a small cell


needs_permissions = pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="chmod 000 does not block root"
)


@needs_permissions
def test_unreadable_file_is_reported_not_skipped(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "concepts/ok.md", "Fine.\n")
    locked = write(root, "manuscripts/main.md", f"Call {phone()}.\n")
    locked.chmod(0)
    try:
        for rule_name, expected in ((None, "phi-unreadable"), ("phi", "phi")):
            findings = scan(
                [root], root=root, settings=ScanSettings(), allow=frozenset(), rule_name=rule_name
            )
            assert [(f.path, f.line, f.rule, f.message) for f in findings] == [
                ("manuscripts/main.md", 0, expected, "file could not be scanned")
            ]
        assert [f.rule for f in lint.run(Vault.load(root), today=TODAY, only=["phi"])] == ["phi"]
        assert [(f.rule, f.line, f.message) for f in validate_path(locked)] == [
            ("phi", 0, "file could not be scanned")
        ]
    finally:
        locked.chmod(0o644)


@needs_permissions
def test_unlistable_directory_is_reported_not_skipped(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "concepts/ok.md", "Fine.\n")
    locked = root / "manuscripts"
    write(root, "manuscripts/main.md", "x\n")
    locked.chmod(0)
    try:
        findings = scan([root], root=root, settings=ScanSettings(), allow=frozenset())
        assert [(f.path, f.line, f.rule, f.message) for f in findings] == [
            ("manuscripts", 0, "phi-unreadable", "file could not be scanned")
        ]
    finally:
        locked.chmod(0o755)


def test_non_utf8_denylist_is_a_config_error(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    (root / ".labbrain" / "phi-denylist.txt").write_bytes(b"Zebulon Quixley\n\xff\xfe\n")
    with pytest.raises(ConfigError) as info:
        ScanSettings.from_config(load_config(root), root)
    assert str(info.value) == "phi denylist file cannot be read"
    assert info.value.__suppress_context__


@needs_permissions
def test_unreadable_denylist_is_a_config_error(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    denylist = write(root, ".labbrain/phi-denylist.txt", "Zebulon Quixley\n")
    denylist.chmod(0)
    try:
        with pytest.raises(ConfigError, match=r"\Aphi denylist file cannot be read\Z"):
            ScanSettings.from_config(load_config(root), root)
    finally:
        denylist.chmod(0o644)


def test_paths_without_root_are_reported_as_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, "src/leak.md", f"Call {phone()}.\n")
    monkeypatch.chdir(tmp_path)
    findings = scan([Path("src")], root=None, settings=ScanSettings(), allow=frozenset())
    assert [(f.path, f.rule) for f in findings] == [("src/leak.md", "phi-phone")]


MRN_CONTEXTS = [
    "Patient-ID: {}",
    "patient-id {}",
    "patient_id={}",
    "record # {}",
    "Record #{}",
    "record no. {}",
    "record number {}",
    "Medical records {}",
    "medical records: {}",
    "Patient IDs: {}",
    "patient ids {}",
    "MRNs {}",
    "record nos. {}",
]


@pytest.mark.parametrize("template", MRN_CONTEXTS)
def test_mrn_context_variants(template: str) -> None:
    value = mrn()
    line = template.format(value)
    hits = scan_text(line + "\n", ScanSettings())
    assert [(h.rule, h.col, h.length) for h in hits] == [("phi-mrn", line.index(value) + 1, 8)]


@pytest.mark.parametrize(
    "template",
    ["Recorded {} events in the run.", "The records {} were merged.", "record {} as the run id"],
)
def test_mrn_context_needs_the_whole_word(template: str) -> None:
    """`record` is context only as medical record or with no/number/#, never bare."""
    assert scan_text(template.format(mrn()) + "\n", ScanSettings()) == []


OUTSIDE = "symlinked directory points outside the vault; not scanned"


def _rows(findings: list) -> list[tuple[str, int, str, str]]:
    return [(f.path, f.line, f.rule, f.message) for f in findings]


def test_symlinked_directory_inside_the_vault_is_followed(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "vault")
    write(root, "archive/shared/a.md", f"Call {phone()}.\n")
    write(root, "raw/keep.md", "x\n")
    (root / "raw" / "linked").symlink_to(root / "archive" / "shared", target_is_directory=True)
    sub = scan([root / "raw"], root=root, settings=ScanSettings(), allow=frozenset())
    assert [(f.path, f.rule) for f in sub] == [("raw/linked/a.md", "phi-phone")]
    # A whole-vault scan reports the file once, at its real path.
    whole = scan([root], root=root, settings=ScanSettings(), allow=frozenset())
    assert [(f.path, f.rule) for f in whole] == [("archive/shared/a.md", "phi-phone")]


def test_symlinked_directory_outside_the_vault_is_reported(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "vault")
    write(tmp_path, "ext/a.md", f"Call {phone()}.\n")
    write(root, "raw/keep.md", "x\n")
    (root / "raw" / "linked").symlink_to(tmp_path / "ext", target_is_directory=True)
    for rule_name, expected in ((None, "phi-unreadable"), ("phi", "phi")):
        findings = scan(
            [root], root=root, settings=ScanSettings(), allow=frozenset(), rule_name=rule_name
        )
        assert _rows(findings) == [("raw/linked", 0, expected, OUTSIDE)]


def test_symlink_loop_terminates(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "vault")
    write(root, "raw/a.md", f"Call {phone()}.\n")
    (root / "raw" / "loop").symlink_to(root / "raw", target_is_directory=True)
    (root / "raw" / "up").symlink_to(root, target_is_directory=True)
    findings = scan([root], root=root, settings=ScanSettings(), allow=frozenset())
    assert [(f.path, f.rule) for f in findings] == [("raw/a.md", "phi-phone")]
    # Scanning raw/ follows `up` into the vault but does not re-enter raw/ through it.
    sub = scan([root / "raw"], root=root, settings=ScanSettings(), allow=frozenset())
    assert [(f.path, f.rule) for f in sub] == [("raw/a.md", "phi-phone")]
    # Without a vault the scanned directory is the boundary, so `up` points outside it.
    alone = scan([root / "raw"], root=None, settings=ScanSettings(), allow=frozenset())
    assert [(f.path, f.rule, f.message) for f in alone if f.line == 0] == [
        ((root / "raw" / "up").as_posix(), "phi-unreadable", OUTSIDE)
    ]
    assert [f.rule for f in alone if f.line] == ["phi-phone"]


@needs_permissions
def test_unsearchable_directory_is_reported_not_raised(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "locked/a.md", f"Call {phone()}.\n")
    (root / "locked").chmod(0o444)  # r--: listable, entries cannot be stat'ed or opened
    try:
        findings = scan([root], root=root, settings=ScanSettings(), allow=frozenset())
        assert _rows(findings) == [
            ("locked/a.md", 0, "phi-unreadable", "file could not be scanned")
        ]
    finally:
        (root / "locked").chmod(0o755)


def _vault_texts(vault: Vault) -> dict[Path, str]:
    return {n.path: n.text for n in vault.all_notes() if n.errors != ["cannot read file"]}


def test_pre_read_texts_give_identical_findings(vault_dir: Path) -> None:
    concept = vault_dir / "concepts" / "label-smoothing-calibration.md"
    concept.write_text(
        concept.read_text() + f"\nAsk the steward at {phone()}.\r\nPatient MRN {mrn()}.\n"
    )
    (vault_dir / "concepts" / "nul.md").write_bytes(f"x\0\nCall {phone()}.\n".encode())
    write(vault_dir, "manuscripts/main.md", f"Patient MRN {mrn()}.\n")
    vault = Vault.load(vault_dir)
    kwargs = {
        "root": vault.root,
        "settings": ScanSettings(),
        "allow": frozenset(),
        "rule_name": "phi",
    }
    from_disk = scan([vault.root], **kwargs)
    assert len(from_disk) == 4
    # A .md file with a NUL that is not UTF-16/32 cannot be decoded: reported, not skipped.
    assert ("concepts/nul.md", "text file is not in a readable encoding") in {
        (f.path, f.message) for f in from_disk
    }
    assert scan([vault.root], texts=_vault_texts(vault), **kwargs) == from_disk


def test_pre_read_texts_are_used(tmp_path: Path) -> None:
    root = make_vault(tmp_path).resolve()
    path = write(root, "concepts/a.md", "Clean on disk.\n")
    texts = {path: f"Call {phone()}.\n"}
    findings = scan([root], root=root, settings=ScanSettings(), allow=frozenset(), texts=texts)
    assert [(f.path, f.rule) for f in findings] == [("concepts/a.md", "phi-phone")]


def test_unreadable_allowlist_is_an_allowlist_error_without_content(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    (root / ".labbrain" / "phi-allow.yaml").write_bytes(b"- file: \xff\xfe sentinelvalue\n")
    with pytest.raises(AllowlistError) as info:
        load_allowlist(root)
    assert "sentinelvalue" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


ENCODED = [
    ("utf-16", "utf-16"),  # BOM, native order
    ("utf-16-be-bom", "utf-16-be"),
    ("utf-32", "utf-32"),  # BOM
    ("utf-16-le-no-bom", "utf-16-le"),
    ("utf-16-be-no-bom", "utf-16-be"),
    ("utf-32-le-no-bom", "utf-32-le"),
    ("utf-8-bom", "utf-8-sig"),
]


def _encode(text: str, kind: str, codec: str) -> bytes:
    if kind == "utf-16-be-bom":
        return b"\xfe\xff" + text.encode("utf-16-be")
    return text.encode(codec)


@pytest.mark.parametrize(("kind", "codec"), ENCODED, ids=[k for k, _ in ENCODED])
def test_utf16_and_utf32_text_is_scanned(tmp_path: Path, kind: str, codec: str) -> None:
    value = phone()
    line = f"Call {value} for access."
    root = make_vault(tmp_path)
    path = root / "manuscripts" / "notes.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(_encode(f"intro\n{line}\n", kind, codec))
    findings = scan([root], root=root, settings=ScanSettings(), allow=frozenset())
    assert [(f.path, f.rule, f.line, f.col) for f in findings] == [
        ("manuscripts/notes.txt", "phi-phone", 2, line.index(value) + 1)
    ]
    assert value not in render(findings, "json")


def test_utf16_note_is_scanned_by_lint_and_validate(tmp_path: Path) -> None:
    root = make_vault(tmp_path, MIN_CONFIG + "protected_data: true\n")
    note = root / "concepts" / "wide.md"
    note.parent.mkdir(parents=True)
    note.write_bytes(f"Call {phone()} today.\n".encode("utf-16"))
    assert "phi" in {f.rule for f in lint.run(Vault.load(root), today=TODAY, only=["phi"])}
    assert "phi" in {f.rule for f in validate_path(note)}


def test_text_file_with_unrecognised_nul_bytes_is_reported(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "concepts/ok.md", "Fine.\n")
    blob = b"\x89X" + bytes(RNG.randrange(256) for _ in range(64)) + b"\x00\x00\x07"
    (root / "manuscripts").mkdir()
    (root / "manuscripts" / "table.csv").write_bytes(blob)
    (root / "manuscripts" / "figure.png").write_bytes(blob)
    findings = scan([root], root=root, settings=ScanSettings(), allow=frozenset())
    assert [(f.path, f.rule, f.message) for f in findings] == [
        ("manuscripts/table.csv", "phi-unreadable", "text file is not in a readable encoding")
    ]


def test_only_the_vault_root_index_is_skipped(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "index.md", f"Call {phone()}.\n")
    write(root, "manuscripts/index.md", f"Call {phone()}.\n")
    for target in (root, root / "manuscripts"):
        findings = scan([target], root=root, settings=ScanSettings(), allow=frozenset())
        assert [(f.path, f.rule) for f in findings] == [("manuscripts/index.md", "phi-phone")]
    alone = scan([root / "manuscripts"], root=None, settings=ScanSettings(), allow=frozenset())
    assert [f.rule for f in alone] == ["phi-phone"]
