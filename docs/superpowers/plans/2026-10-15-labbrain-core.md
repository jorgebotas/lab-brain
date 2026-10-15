# labbrain core (M1 + M2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `labbrain` Python package and CLI: vault discovery, config, frontmatter schemas, IDs, note scaffolding, validation, supersession sync, index, daily log, 16 lint rules and a PHI scanner. Each broken fixture must trigger exactly its own lint rule, and the valid fixture must yield zero findings.

**Architecture:** One parse pass loads every note into a `Vault` graph (notes keyed by filename stem, inbound/outbound link maps). Lint rules are pure functions `rule(ctx) -> Iterable[Finding]`, registered with a decorator and discovered automatically. `schema.py` knows nothing about config or the filesystem; every context-dependent check is a lint rule. Reads use PyYAML's libyaml-backed safe loader (measured 0.5 s per 3,000 notes; ruamel's loader is pure Python since 0.19 and takes 6 s); writes use ruamel round-trip mode so a one-field edit is a one-line diff.

**Tech Stack:** Python ≥3.11, pydantic v2, PyYAML (reads), ruamel.yaml (writes), argparse, pytest, pytest-cov, ruff, uv, git CLI.

**Spec:** `docs/superpowers/specs/2026-10-15-labbrain-core-design.md` (read it first; this plan implements it exactly).

## Global Constraints

- Python `>=3.11`. Runtime dependencies: exactly `pydantic>=2.6,<3`, `pyyaml>=6` (fast reads via libyaml) and `ruamel.yaml>=0.18` (comment-preserving writes). No others.
- Dev dependencies: `pytest>=8`, `pytest-cov>=5`, `ruff>=0.6`, `pre-commit>=3`.
- Type hints on every function. `from __future__ import annotations` at the top of every module.
- ruff: line length 100 (enforced by `ruff format`; E501 ignored because hash literals cannot wrap), target `py311`, rules `E,F,I,UP,B`. `uv run ruff check .` and `uv run ruff format --check .` must pass at the end of every task.
- Exit codes everywhere: `0` no error findings, `1` at least one error finding, `2` usage or config problem.
- **No finding message, error message or CLI output may contain a frontmatter field value or matched PHI text.** Every message passes through `findings.sanitize`. pydantic errors are rendered with `include_input=False, include_url=False, include_context=False`.
- `labbrain/cli.py` imports nothing beyond the standard library and `labbrain`/`labbrain.layout` at module level.
- YAML reads go through `labbrain.notes.safe_load` (PyYAML `CSafeLoader`, falling back to `SafeLoader`); only `update_frontmatter`/`render_note` use ruamel.
- Time comes from `labbrain.vault.now()`, which honours `LABBRAIN_NOW` (ISO datetime). Tests pin `LABBRAIN_NOW=2026-10-15T12:00:00`.
- Budgets: `lint` < 3 s on 3,000 notes; `validate` on one file < 300 ms.
- Commits: conventional commit messages. Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; the commit commands below pass it as a second `-m`.
- Never put a real-looking identifier (phone, MRN, SSN, email, address) in any file outside `tests/` and `docs/superpowers/`. Tests generate synthetic identifiers from a seeded RNG.

## File Map

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml`, `.gitignore`, `.python-version`, `README.md`, `.github/workflows/ci.yml` | Packaging, tooling, CI | 1, 17 |
| `labbrain/__init__.py` | `__version__` | 1 |
| `labbrain/findings.py` | `Finding`, `sanitize`, renderers, exit codes | 1 |
| `labbrain/layout.py` | Folder names, note types, note-path predicates | 2 |
| `labbrain/ids.py` | Slugs, ID regexes, collision-safe minting | 2 |
| `labbrain/schema.py` | pydantic models, section/status registries, `validate_frontmatter` | 3 |
| `labbrain/notes.py` | `Note`, frontmatter split, YAML read/write, links, sections | 4 |
| `labbrain/vault.py` | Discovery, `Config`, `now()`, `Vault` graph | 5 |
| `labbrain/lint/__init__.py` | Rule registry and runner | 7 |
| `labbrain/lint/rules/schema_rules.py` | `schema`, `missing-section`, `check_note` | 7 |
| `labbrain/validate.py` | Single-file validation | 7, 14 |
| `labbrain/lint/rules/link_rules.py` | `broken-link`, `orphan` | 8 |
| `labbrain/lint/rules/protocol_rules.py` | `protocol-missing`, `cross-protocol`, `claim-stale`, `duplicate-config`, `sync-pending` | 9, 10 |
| `labbrain/sync.py` | Supersession propagation, protocol freezing | 10 |
| `labbrain/index.py`, `labbrain/log.py` | `index.md`, daily log | 11 |
| `labbrain/lint/rules/hygiene_rules.py` | `index-stale`, `concept-unsourced`, `inbox-age`, `dirty-code`, `undated-fact` | 11, 12 |
| `labbrain/gitutil.py`, `labbrain/lint/rules/frozen_rules.py` | Base-revision reads, `frozen-edit` | 13 |
| `labbrain/phi.py`, `labbrain/lint/rules/phi_rules.py` | Scanner, allowlist, `phi` | 14 |
| `labbrain/scaffold.py`, `labbrain/query.py`, `labbrain/confighash.py` | `new`, `list`/`links`, `config-hash` | 15 |
| `labbrain/cli.py`, `labbrain/__main__.py` | Command line | 16 |
| `.pre-commit-hooks.yaml` | Hooks consumable by vault repos | 17 |
| `docs/decisions/ADR-20261015-*.md`, `CHANGELOG.md` | Engine ADRs, changelog | 18 |
| `tests/helpers.py`, `tests/conftest.py` | Shared test helpers and fixtures | 5, 6 |
| `tests/fixtures/valid/**` | Static valid vault | 6, 11 |
| `tests/fixtures/mutations.py` | One named mutation per lint rule | 6–14 |

---

### Task 1: Project scaffold and findings

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.python-version`, `README.md`, `.github/workflows/ci.yml`
- Create: `labbrain/__init__.py`, `labbrain/findings.py`
- Test: `tests/test_findings.py`

**Interfaces:**
- Produces: `labbrain.__version__ == "0.1.0"`.
- Produces (`labbrain.findings`): constants `ERROR`, `WARNING`, `INFO`; `sanitize(message: str) -> str`; frozen dataclass `Finding(path: str, line: int, rule: str, severity: str, message: str, col: int = 0)` with `sort_key()` and `to_dict()`; `sort_findings(findings) -> list[Finding]`; `summarize(findings) -> dict[str, int]` (keys `errors`, `warnings`, `info`); `exit_code(findings) -> int`; `render(findings, fmt: str) -> str` for `fmt` in `text|json|github`.

- [ ] **Step 1: Create packaging and tooling files**

`pyproject.toml`:

```toml
[project]
name = "labbrain"
dynamic = ["version"]
description = "Deterministic core of lab-brain: schemas, IDs, validation, lint and PHI scanning for ML research vaults"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [{ name = "jorgebotas" }]
dependencies = [
    "pydantic>=2.6,<3",
    "pyyaml>=6",
    "ruamel.yaml>=0.18",
]

[project.scripts]
labbrain = "labbrain.cli:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.version]
path = "labbrain/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["labbrain"]

[dependency-groups]
dev = ["pytest>=8", "pytest-cov>=5", "ruff>=0.6", "pre-commit>=3"]

[tool.pytest.ini_options]
pythonpath = ["tests"]
testpaths = ["tests"]
markers = [
    "slow: performance-budget tests",
    "network: needs network access (pre-commit try-repo)",
]

[tool.coverage.run]
source = ["labbrain"]

[tool.coverage.report]
include = [
    "*/labbrain/schema.py",
    "*/labbrain/ids.py",
    "*/labbrain/vault.py",
    "*/labbrain/phi.py",
    "*/labbrain/lint/*",
]
show_missing = true

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]  # the formatter owns line length; long literals (hashes) cannot wrap
```

`.gitignore`:

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.coverage
coverage.xml
dist/
build/
```

`.python-version`:

```
3.11
```

`README.md`:

```markdown
# lab-brain

Engine for lab-brain, a Claude Code–maintained second brain for ML research projects.

This repository currently contains `labbrain`, the deterministic Python core: schemas, IDs,
validation, lint and PHI scanning for lab-brain vaults. Skills, hooks and the plugin manifest
arrive in later releases.

## Development

    uv sync
    uv run pytest
    uv run labbrain --help

The PHI guardrails make the safe path the default. They do not replace your institution's
DUA, IRB or security rules.
```

`labbrain/__init__.py`:

```python
"""lab-brain deterministic core."""

__version__ = "0.1.0"
```

`.github/workflows/ci.yml`:

```yaml
name: ci
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.11", "3.13"]
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
```

- [ ] **Step 2: Write the failing tests**

`tests/test_findings.py`:

```python
from __future__ import annotations

import json

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv sync && uv run pytest tests/test_findings.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'labbrain.findings'`.

- [ ] **Step 4: Implement `labbrain/findings.py`**

```python
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


def sanitize(message: str) -> str:
    """Strip control characters, redact identifier-like tokens, cap the length."""
    text = _CONTROL.sub(" ", message)
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_findings.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: 11 passed; ruff clean (run `uv run ruff format .` first if the format check complains).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore .python-version README.md .github labbrain tests
git commit -m "feat(core): scaffold labbrain package and findings module" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Layout constants and IDs

**Files:**
- Create: `labbrain/layout.py`, `labbrain/ids.py`
- Test: `tests/test_layout.py`, `tests/test_ids.py`

**Interfaces:**
- Produces (`labbrain.layout`): `NOTE_TYPES: tuple[str, ...]` (order: experiment, protocol, claim, idea, concept, decision, literature, handoff, dataset); `TYPE_FOLDERS: dict[str, str]`; `NOTE_FOLDERS: tuple[str, ...]`; `NON_NOTE_FILENAMES`; `CONFIG_PATH = ".labbrain/config.yaml"`; `ALLOWLIST_PATH = ".labbrain/phi-allow.yaml"`; `INDEX_FILE = "index.md"`; `LOG_DIR = "log"`; `RAW_DIR = "raw"`; `PHI_SKIP_DIR_NAMES`; `PHI_SKIP_FILES`; `is_note_rel(rel: str) -> bool`; `iter_note_files(root: Path) -> Iterator[Path]`.
- Produces (`labbrain.ids`): `SLUG_MAX = 40`; `DEFAULT_PREFIXES: dict[str, str]`; `DATED_TYPES`; `IdError(ValueError)`; `slugify(text, max_len=40, fallback="untitled") -> str`; `id_regex(note_type, prefixes=None) -> re.Pattern`; `is_valid_id(note_id, note_type, prefixes=None) -> bool`; `existing_ids(root) -> set[str]`; `new_id(note_type, *, root, now, title="", prefixes=None, agent="", first_author="", year=None, name="") -> str`; `protocol_version(note_id, prefixes=None) -> int | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_layout.py`:

```python
from __future__ import annotations

from pathlib import Path

from labbrain.layout import NOTE_TYPES, TYPE_FOLDERS, is_note_rel, iter_note_files


def test_every_type_has_a_folder() -> None:
    assert set(TYPE_FOLDERS) == set(NOTE_TYPES)


def test_is_note_rel() -> None:
    assert is_note_rel("experiments/EXP-20261013-x.md")
    assert is_note_rel("ideas/archive/IDEA-20261013-x.md")
    assert not is_note_rel("experiments/README.md")
    assert not is_note_rel("raw/papers/x.md")
    assert not is_note_rel("index.md")
    assert not is_note_rel("experiments/figure.png")


def test_iter_note_files_skips_readmes_and_other_folders(tmp_path: Path) -> None:
    for rel in [
        "experiments/EXP-20261013-a.md",
        "experiments/README.md",
        "ideas/archive/IDEA-20261013-b.md",
        "raw/notes.md",
        "scratch/alice/c.md",
        "index.md",
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    found = [p.relative_to(tmp_path).as_posix() for p in iter_note_files(tmp_path)]
    assert found == ["experiments/EXP-20261013-a.md", "ideas/archive/IDEA-20261013-b.md"]
```

`tests/test_ids.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from labbrain.ids import IdError, is_valid_id, new_id, protocol_version, slugify

NOW = datetime(2026, 10, 13, 14, 20)


def touch(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n---\n")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Label smoothing vs. calibration", "label-smoothing-vs-calibration"),
        ("  Curriculum -- by   length!! ", "curriculum-by-length"),
        ("Müller–Ångström", "muller-angstrom"),
        ("李明", "untitled"),
        ("", "untitled"),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_slugify_truncates_at_word_boundary() -> None:
    slug = slugify("a very long title about tempered decoding in sequence models today")
    assert slug == "a-very-long-title-about-tempered"


def test_dated_ids(tmp_path: Path) -> None:
    def mint(t: str, title: str) -> str:
        return new_id(t, root=tmp_path, now=NOW, title=title)

    assert mint("experiment", "Label smoothing") == "EXP-20261013-label-smoothing"
    assert mint("claim", "Median AUROC") == "CLM-20261013-median-auroc"
    assert mint("idea", "Curriculum by length") == "IDEA-20261013-curriculum-by-length"
    assert mint("decision", "Tracker choice") == "ADR-20261013-tracker-choice"
    assert mint("dataset", "Main split") == "DS-20261013-main-split"


def test_collision_scans_every_note_folder(tmp_path: Path) -> None:
    touch(tmp_path, "experiments/EXP-20261013-label-smoothing.md")
    touch(tmp_path, "ideas/archive/EXP-20261013-label-smoothing-2.md")
    got = new_id("experiment", root=tmp_path, now=NOW, title="Label smoothing")
    assert got == "EXP-20261013-label-smoothing-3"


def test_collision_suffix_respects_slug_max(tmp_path: Path) -> None:
    slug = "abcdefghij-abcdefghij-abcdefghij-abcdefg"
    assert len(slug) == 40
    touch(tmp_path, f"experiments/EXP-20261013-{slug}.md")
    got = new_id("experiment", root=tmp_path, now=NOW, title=slug)
    assert got == "EXP-20261013-abcdefghij-abcdefghij-abcdefghij-2"
    assert is_valid_id(got, "experiment")


def test_protocol_numbering(tmp_path: Path) -> None:
    assert new_id("protocol", root=tmp_path, now=NOW) == "EVAL-v1"
    touch(tmp_path, "protocols/EVAL-v1.md")
    touch(tmp_path, "protocols/EVAL-v3-masked.md")
    assert new_id("protocol", root=tmp_path, now=NOW) == "EVAL-v4"
    assert new_id("protocol", root=tmp_path, now=NOW, name="Masked AUROC") == "EVAL-v4-masked-auroc"
    assert protocol_version("EVAL-v3-masked") == 3
    assert protocol_version("EXP-20261013-x") is None


def test_literature_ids(tmp_path: Path) -> None:
    got = new_id(
        "literature",
        root=tmp_path,
        now=NOW,
        title="Attention Is All You Need",
        first_author="Vaswani",
        year=2017,
    )
    assert got == "LIT-vaswani2017-attention"
    got = new_id(
        "literature",
        root=tmp_path,
        now=NOW,
        title="On the Rethinking of X",
        first_author="van der Waals",
        year=2016,
    )
    assert got == "LIT-vanderwaals2016-rethinking"
    with pytest.raises(IdError):
        new_id("literature", root=tmp_path, now=NOW, title="x", first_author="a")


def test_handoff_and_concept_ids(tmp_path: Path) -> None:
    assert new_id("handoff", root=tmp_path, now=NOW, agent="claude") == "HO-20261013-1420-claude"
    assert new_id("concept", root=tmp_path, now=NOW, title="Tempered decoding") == "tempered-decoding"


def test_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(IdError):
        new_id("memo", root=tmp_path, now=NOW, title="x")


@pytest.mark.parametrize(
    ("note_id", "note_type", "ok"),
    [
        ("EXP-20261013-label-smoothing", "experiment", True),
        ("EXP-2026101-label", "experiment", False),
        ("EXP-20261013-Label", "experiment", False),
        ("EVAL-v3", "protocol", True),
        ("EVAL-v3-masked", "protocol", True),
        ("EVAL-v0", "protocol", False),
        ("LIT-vaswani2017-attention", "literature", True),
        ("LIT-vaswani17-attention", "literature", False),
        ("HO-20261013-1420-claude", "handoff", True),
        ("tempered-decoding", "concept", True),
        ("Tempered", "concept", False),
        ("DS-20260801-main-split", "dataset", True),
        ("EXP-20261013-" + "a" * 41, "experiment", False),
    ],
)
def test_is_valid_id(note_id: str, note_type: str, ok: bool) -> None:
    assert is_valid_id(note_id, note_type) is ok


def test_custom_prefixes() -> None:
    assert is_valid_id("RUN-20261013-x", "experiment", {"experiment": "RUN"})
    assert not is_valid_id("EXP-20261013-x", "experiment", {"experiment": "RUN"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout.py tests/test_ids.py -v`
Expected: collection errors, `ModuleNotFoundError: No module named 'labbrain.layout'`.

- [ ] **Step 3: Implement `labbrain/layout.py`**

```python
"""Vault layout: folder names, note types, skip lists, and note-path predicates.

Pure standard library so the CLI can import it without pulling in pydantic.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePosixPath

NOTE_TYPES: tuple[str, ...] = (
    "experiment",
    "protocol",
    "claim",
    "idea",
    "concept",
    "decision",
    "literature",
    "handoff",
    "dataset",
)

# Where `labbrain new` puts each type. Ideas start in the inbox.
TYPE_FOLDERS: dict[str, str] = {
    "experiment": "experiments",
    "protocol": "protocols",
    "claim": "claims",
    "idea": "ideas/inbox",
    "concept": "concepts",
    "decision": "decisions",
    "literature": "literature",
    "handoff": "handoffs",
    "dataset": "datasets",
}

# Top-level folders that hold notes; searched recursively.
NOTE_FOLDERS: tuple[str, ...] = (
    "experiments",
    "protocols",
    "claims",
    "ideas",
    "concepts",
    "decisions",
    "literature",
    "handoffs",
    "datasets",
)
NON_NOTE_FILENAMES: frozenset[str] = frozenset({"README.md"})

CONFIG_PATH = ".labbrain/config.yaml"
ALLOWLIST_PATH = ".labbrain/phi-allow.yaml"
INDEX_FILE = "index.md"
LOG_DIR = "log"
RAW_DIR = "raw"

# phi-scan skips these directory names (and every dot-directory) at any depth,
# and these file names at the top of the scanned tree.
PHI_SKIP_DIR_NAMES: frozenset[str] = frozenset({"scratch", "__pycache__", "node_modules"})
PHI_SKIP_FILES: frozenset[str] = frozenset({INDEX_FILE})


def is_note_rel(rel: str) -> bool:
    """True if a vault-relative POSIX path is a note location."""
    path = PurePosixPath(rel)
    return (
        len(path.parts) >= 2
        and path.parts[0] in NOTE_FOLDERS
        and path.suffix == ".md"
        and path.name not in NON_NOTE_FILENAMES
    )


def iter_note_files(root: Path) -> Iterator[Path]:
    """Every candidate note file under the note folders, in a stable order."""
    for folder in NOTE_FOLDERS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.is_file() and path.name not in NON_NOTE_FILENAMES:
                yield path
```

- [ ] **Step 4: Implement `labbrain/ids.py`**

```python
"""ID formats, slugs and collision-safe ID minting.

IDs are date + slug, never counters, so two lab members on separate branches
cannot mint the same ID. The one exception is protocol versions (EVAL-v<N>),
which are created rarely and by hand; a clash is caught by the duplicate-ID check.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from labbrain.layout import iter_note_files

SLUG_MAX = 40
SLUG_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
DEFAULT_PREFIXES: dict[str, str] = {
    "experiment": "EXP",
    "protocol": "EVAL",
    "claim": "CLM",
    "idea": "IDEA",
    "decision": "ADR",
    "literature": "LIT",
    "handoff": "HO",
    "dataset": "DS",
}
DATED_TYPES: frozenset[str] = frozenset({"experiment", "claim", "idea", "decision", "dataset"})
_STOPWORDS = frozenset(
    {"a", "an", "the", "on", "of", "for", "in", "to", "and", "with", "via", "towards", "toward",
     "is", "are", "from", "by", "at"}
)


class IdError(ValueError):
    """An ID cannot be minted from the given inputs."""


def slugify(text: str, max_len: int = SLUG_MAX, fallback: str = "untitled") -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return _truncate(slug, max_len) or fallback


def _truncate(slug: str, max_len: int) -> str:
    if len(slug) <= max_len:
        return slug
    cut = slug[:max_len]
    if slug[max_len] != "-" and "-" in cut:
        cut = cut.rsplit("-", 1)[0]
    return cut.strip("-")


def _prefixes(prefixes: Mapping[str, str] | None) -> dict[str, str]:
    return {**DEFAULT_PREFIXES, **(prefixes or {})}


def id_regex(note_type: str, prefixes: Mapping[str, str] | None = None) -> re.Pattern[str]:
    slug = f"(?P<slug>{SLUG_PATTERN})"
    if note_type == "concept":
        return re.compile(rf"\A{slug}\Z")
    try:
        p = re.escape(_prefixes(prefixes)[note_type])
    except KeyError as exc:
        raise IdError(f"unknown note type: {note_type}") from exc
    if note_type in DATED_TYPES:
        pattern = rf"{p}-\d{{8}}-{slug}"
    elif note_type == "protocol":
        pattern = rf"{p}-v[1-9]\d*(?:-{slug})?"
    elif note_type == "literature":
        pattern = rf"{p}-[a-z]+\d{{4}}-{slug}"
    else:  # handoff
        pattern = rf"{p}-\d{{8}}-\d{{4}}-{slug}"
    return re.compile(rf"\A{pattern}\Z")


def is_valid_id(note_id: str, note_type: str, prefixes: Mapping[str, str] | None = None) -> bool:
    match = id_regex(note_type, prefixes).match(note_id)
    return match is not None and len(match.group("slug") or "") <= SLUG_MAX


def existing_ids(root: Path) -> set[str]:
    """Filename stems of every note in the working tree, tracked or not."""
    return {path.stem for path in iter_note_files(root)}


def protocol_version(note_id: str, prefixes: Mapping[str, str] | None = None) -> int | None:
    prefix = re.escape(_prefixes(prefixes)["protocol"])
    match = re.match(rf"\A{prefix}-v([1-9]\d*)(?:-|\Z)", note_id)
    return int(match.group(1)) if match else None


def new_id(
    note_type: str,
    *,
    root: Path,
    now: datetime,
    title: str = "",
    prefixes: Mapping[str, str] | None = None,
    agent: str = "",
    first_author: str = "",
    year: int | None = None,
    name: str = "",
) -> str:
    pre = _prefixes(prefixes)
    taken = existing_ids(root)
    if note_type in DATED_TYPES:
        stamp = now.strftime("%Y%m%d")
        return _first_free(lambda s: f"{pre[note_type]}-{stamp}-{s}", slugify(title), taken)
    if note_type == "protocol":
        return _next_protocol(pre["protocol"], taken, name, prefixes)
    if note_type == "literature":
        if year is None or not 1000 <= year <= 9999:
            raise IdError("literature IDs need a four-digit year")
        author = re.sub(r"[^a-z]", "", slugify(first_author, fallback="")) or "anon"
        word = _first_significant_word(title)
        return _first_free(lambda s: f"{pre['literature']}-{author}{year}-{s}", word, taken)
    if note_type == "handoff":
        stamp = now.strftime("%Y%m%d-%H%M")
        agent_slug = slugify(agent, fallback="agent")
        return _first_free(lambda s: f"{pre['handoff']}-{stamp}-{s}", agent_slug, taken)
    if note_type == "concept":
        return _first_free(lambda s: s, slugify(title), taken)
    raise IdError(f"unknown note type: {note_type}")


def _first_significant_word(title: str) -> str:
    for word in slugify(title, max_len=10_000, fallback="").split("-"):
        if word and word not in _STOPWORDS:
            return word[:SLUG_MAX]
    return "untitled"


def _first_free(compose: Callable[[str], str], slug: str, taken: set[str]) -> str:
    candidate = compose(slug)
    k = 2
    while candidate in taken:
        suffix = f"-{k}"
        candidate = compose(_truncate(slug, SLUG_MAX - len(suffix)) + suffix)
        k += 1
    return candidate


def _next_protocol(
    prefix: str, taken: set[str], name: str, prefixes: Mapping[str, str] | None
) -> str:
    numbers = [n for t in taken if (n := protocol_version(t, prefixes)) is not None]
    base = f"{prefix}-v{max(numbers, default=0) + 1}"
    if not name:
        return base
    return _first_free(lambda s: f"{base}-{s}", slugify(name), taken)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout.py tests/test_ids.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add labbrain/layout.py labbrain/ids.py tests/test_layout.py tests/test_ids.py
git commit -m "feat(ids): layout constants and collision-safe ID minting" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Frontmatter schemas

**Files:**
- Create: `labbrain/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: `labbrain.layout.NOTE_TYPES`.
- Produces (`labbrain.schema`): models `BaseNote`, `ExperimentNote`, `ProtocolNote`, `ClaimNote`, `IdeaNote`, `ConceptNote`, `DecisionNote`, `LiteratureNote`, `HandoffNote`, `DatasetNote`, plus nested `Tracker`, `Code`, `Metric`; `MODELS: dict[str, type[BaseNote]]`; `REQUIRED_SECTIONS: dict[str, tuple[str, ...]]`; `DEFAULT_STATUS: dict[str, str]`; `FUTURE_AGENTS_HEADING = "For future agents"`; `ID_FIELDS: tuple[str, ...]`; `validate_frontmatter(data: dict) -> tuple[BaseNote | None, list[str]]` (messages formatted `"<loc>: <msg>"`, `loc` = `"frontmatter"` for model-level errors); `json_schema(note_type: str | None = None) -> dict`.

- [ ] **Step 1: Write the failing tests**

`tests/test_schema.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from labbrain.layout import NOTE_TYPES
from labbrain.schema import (
    DEFAULT_STATUS,
    MODELS,
    REQUIRED_SECTIONS,
    ExperimentNote,
    json_schema,
    validate_frontmatter,
)

MINIMAL: dict[str, dict[str, Any]] = {"protocol": {"version": 1}, "concept": {"sources": []}}


def common(note_type: str, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "x",
        "type": note_type,
        "title": "T",
        "created": date(2026, 10, 13),
        "updated": date(2026, 10, 13),
        "author": "alice",
        "status": DEFAULT_STATUS[note_type],
    }
    data.update(MINIMAL.get(note_type, {}))
    data.update(extra)
    return data


@pytest.mark.parametrize("note_type", NOTE_TYPES)
def test_minimal_note_of_each_type_validates(note_type: str) -> None:
    model, errors = validate_frontmatter(common(note_type))
    assert errors == []
    assert model is not None


def test_registries_cover_every_type() -> None:
    assert set(MODELS) == set(REQUIRED_SECTIONS) == set(DEFAULT_STATUS) == set(NOTE_TYPES)


def test_unknown_type() -> None:
    model, errors = validate_frontmatter({"type": "memo"})
    assert model is None
    assert errors == ["type: must be one of " + ", ".join(NOTE_TYPES)]


def test_bad_status_message_does_not_echo_input() -> None:
    _, errors = validate_frontmatter(common("experiment", status="archived-123456789"))
    assert len(errors) == 1
    assert errors[0].startswith("status: Input should be")
    assert "archived-123456789" not in errors[0]


def test_done_experiment_requires_dataset_but_not_protocol() -> None:
    _, errors = validate_frontmatter(common("experiment", status="done", protocol="EVAL-v1"))
    assert errors == ["frontmatter: dataset is required when status is done"]
    _, errors = validate_frontmatter(common("experiment", status="done", dataset="DS-1"))
    assert errors == []  # protocol-missing is a lint rule, not a model error


@pytest.mark.parametrize("note_type", ["experiment", "decision", "dataset"])
def test_superseded_requires_superseded_by(note_type: str) -> None:
    _, errors = validate_frontmatter(common(note_type, status="superseded"))
    assert errors == ["frontmatter: superseded_by is required when status is superseded"]
    _, errors = validate_frontmatter(common(note_type, status="superseded", superseded_by="X"))
    assert errors == []


def test_consolidated_idea_requires_target() -> None:
    _, errors = validate_frontmatter(common("idea", status="consolidated"))
    assert errors == ["frontmatter: consolidated_into is required when status is consolidated"]


def test_concept_sources_key_required_but_may_be_empty() -> None:
    data = common("concept")
    del data["sources"]
    assert validate_frontmatter(data)[1] == ["sources: Field required"]
    assert validate_frontmatter(common("concept", sources=None))[1] == []


def test_unknown_fields_preserved() -> None:
    model, _ = validate_frontmatter(common("idea", project_field="kept"))
    assert model is not None
    assert model.model_extra == {"project_field": "kept"}


def test_nested_models_and_coercions() -> None:
    model, errors = validate_frontmatter(
        common(
            "experiment",
            code={"sha": 1234567, "dirty": False},
            tracker={"backend": "local", "run_ids": ["r1"]},
            metrics=[{"name": "auroc", "value": 0.81, "run_id": "r1", "as_of": "2026-10-13"}],
        )
    )
    assert errors == []
    assert isinstance(model, ExperimentNote)
    assert model.code is not None and model.code.sha == "1234567"
    assert model.metrics[0].as_of == date(2026, 10, 13)


def test_field_constraints() -> None:
    _, errors = validate_frontmatter(common("experiment", code={"sha": "not-hex"}))
    assert len(errors) == 1 and errors[0].startswith("code.sha:")
    _, errors = validate_frontmatter(common("claim", tolerance=-1))
    assert len(errors) == 1 and errors[0].startswith("tolerance:")
    _, errors = validate_frontmatter(common("protocol", version=0))
    assert len(errors) == 1 and errors[0].startswith("version:")


def test_null_list_fields_become_empty() -> None:
    model, errors = validate_frontmatter(common("experiment", tags=None, links=None, metrics=None))
    assert errors == []
    assert isinstance(model, ExperimentNote)
    assert model.tags == [] and model.metrics == []


def test_json_schema_export() -> None:
    assert json_schema("experiment")["title"] == "ExperimentNote"
    assert "oneOf" in json_schema()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_schema.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'labbrain.schema'`.

- [ ] **Step 3: Implement `labbrain/schema.py`**

```python
"""Frontmatter models, one per note type.

These models know nothing about config or the filesystem: they check shape,
types and status enums only. Context-dependent checks (ID format against
configured prefixes, id == filename, author membership, links) live in the
lint rules. Unknown fields are allowed and preserved so projects can extend
schemas without forking the engine.
"""

from __future__ import annotations

import typing
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from labbrain.layout import NOTE_TYPES

FUTURE_AGENTS_HEADING = "For future agents"

# Frontmatter fields whose values are note IDs (scalars or lists).
ID_FIELDS: tuple[str, ...] = (
    "links",
    "evidence",
    "sources",
    "protocol",
    "dataset",
    "supersedes",
    "superseded_by",
    "consolidated_into",
    "split_of",
    "changes_from",
    "comparable_with",
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _null_lists_are_empty(cls, data: Any) -> Any:
        """Treat `key:` (YAML null) as an empty list for list-typed fields."""
        if isinstance(data, dict):
            for name, field in cls.model_fields.items():
                if data.get(name, ...) is None and typing.get_origin(field.annotation) is list:
                    data = {**data, name: []}
        return data


class Tracker(_Model):
    backend: str | None = None
    run_ids: list[str] = []
    url: str | None = None


class Code(_Model):
    repo: str | None = None
    sha: str | None = Field(default=None, pattern=r"\A[0-9a-f]{7,40}\Z")
    dirty: bool | None = None

    @field_validator("sha", mode="before")
    @classmethod
    def _sha_as_text(cls, value: Any) -> Any:
        return str(value) if isinstance(value, int) and not isinstance(value, bool) else value


class Metric(_Model):
    name: str
    value: float
    split: str | None = None
    run_id: str | None = None
    as_of: date | None = None


class BaseNote(_Model):
    id: str
    type: str
    title: str
    created: date
    updated: date
    author: str
    status: str
    tags: list[str] = []
    links: list[str] = []


def _require_when(note: BaseNote, status: str, field: str) -> None:
    if note.status == status and not getattr(note, field, None):
        raise ValueError(f"{field} is required when status is {status}")


class ExperimentNote(BaseNote):
    type: Literal["experiment"]
    status: Literal["planned", "running", "done", "failed", "superseded"]
    hypothesis: str | None = None
    protocol: str | None = None
    tracker: Tracker | None = None
    code: Code | None = None
    config_hash: str | None = None
    dataset: str | None = None
    metrics: list[Metric] = []
    supersedes: str | None = None
    superseded_by: str | None = None

    @model_validator(mode="after")
    def _conditionals(self) -> ExperimentNote:
        _require_when(self, "done", "dataset")
        _require_when(self, "superseded", "superseded_by")
        return self


class ProtocolNote(BaseNote):
    type: Literal["protocol"]
    status: Literal["draft", "frozen", "retired"]
    version: int = Field(ge=1)
    changes_from: str | None = None
    comparable_with: list[str] = []


class ClaimNote(BaseNote):
    type: Literal["claim"]
    status: Literal["draft", "supported", "stale", "retracted"]
    statement: str | None = None
    value: float | list[float] | None = None
    value_format: str | None = None
    tolerance: float | None = Field(default=None, ge=0)
    evidence: list[str] = []
    protocol: str | None = None
    manuscript_locations: list[str] = []


class IdeaNote(BaseNote):
    type: Literal["idea"]
    status: Literal["open", "consolidated", "dropped"]
    consolidated_into: str | None = None

    @model_validator(mode="after")
    def _conditionals(self) -> IdeaNote:
        _require_when(self, "consolidated", "consolidated_into")
        return self


class ConceptNote(BaseNote):
    type: Literal["concept"]
    status: Literal["active", "stale"]
    sources: list[str]


class DecisionNote(BaseNote):
    type: Literal["decision"]
    status: Literal["proposed", "accepted", "superseded"]
    supersedes: str | None = None
    superseded_by: str | None = None

    @model_validator(mode="after")
    def _conditionals(self) -> DecisionNote:
        _require_when(self, "superseded", "superseded_by")
        return self


class LiteratureNote(BaseNote):
    type: Literal["literature"]
    status: Literal["active", "stale"]
    doi: str | None = None
    arxiv: str | None = None
    url: str | None = None
    year: int | None = Field(default=None, ge=1000, le=9999)
    venue: str | None = None
    relevance: Literal["high", "medium", "low"] | None = None


class HandoffNote(BaseNote):
    type: Literal["handoff"]
    status: Literal["final"]
    agent: str | None = None
    session_goal: str | None = None
    files_touched: list[str] = []


class DatasetNote(BaseNote):
    type: Literal["dataset"]
    status: Literal["active", "superseded"]
    location: str | None = None
    extracted: date | None = None
    split_of: str | None = None
    counts: dict[str, Any] | None = None
    protected: bool | None = None
    supersedes: str | None = None
    superseded_by: str | None = None

    @model_validator(mode="after")
    def _conditionals(self) -> DatasetNote:
        _require_when(self, "superseded", "superseded_by")
        return self


MODELS: dict[str, type[BaseNote]] = {
    "experiment": ExperimentNote,
    "protocol": ProtocolNote,
    "claim": ClaimNote,
    "idea": IdeaNote,
    "concept": ConceptNote,
    "decision": DecisionNote,
    "literature": LiteratureNote,
    "handoff": HandoffNote,
    "dataset": DatasetNote,
}

AnyNote = Annotated[
    Union[  # noqa: UP007 - discriminated unions read better spelled out
        ExperimentNote,
        ProtocolNote,
        ClaimNote,
        IdeaNote,
        ConceptNote,
        DecisionNote,
        LiteratureNote,
        HandoffNote,
        DatasetNote,
    ],
    Field(discriminator="type"),
]

REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "experiment": ("Hypothesis", "Setup", "Results", "Interpretation", "Next"),
    "protocol": ("Definition", "Changes from previous version", "Known caveats"),
    "claim": ("Evidence summary", "History"),
    "idea": (),
    "concept": ("Summary", "Evidence", "Open questions", "Related"),
    "decision": ("Context", "Decision", "Alternatives considered", "Consequences"),
    "literature": (
        "Summary",
        "Methods worth borrowing",
        "Results to compare against",
        "Style notes",
    ),
    "handoff": ("Done", "In progress", "Blockers", "Next step for whoever picks this up"),
    "dataset": ("Source", "Inclusion and exclusion", "Split definition", "Known issues"),
}

DEFAULT_STATUS: dict[str, str] = {
    "experiment": "planned",
    "protocol": "draft",
    "claim": "draft",
    "idea": "open",
    "concept": "active",
    "decision": "proposed",
    "literature": "active",
    "handoff": "final",
    "dataset": "active",
}

assert set(MODELS) == set(NOTE_TYPES)


def _format_error(error: Any) -> str:
    loc = ".".join(str(part) for part in error["loc"]) or "frontmatter"
    return f"{loc}: {error['msg'].removeprefix('Value error, ')}"


def validate_frontmatter(data: dict[str, Any]) -> tuple[BaseNote | None, list[str]]:
    """Validate a frontmatter dict. Error messages never contain input values."""
    note_type = data.get("type")
    model = MODELS.get(note_type) if isinstance(note_type, str) else None
    if model is None:
        return None, [f"type: must be one of {', '.join(NOTE_TYPES)}"]
    try:
        return model.model_validate(data), []
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        return None, [_format_error(e) for e in errors]


def json_schema(note_type: str | None = None) -> dict[str, Any]:
    if note_type is None:
        return TypeAdapter(AnyNote).json_schema()
    return MODELS[note_type].model_json_schema()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass. If `test_bad_status_message_does_not_echo_input` fails because the installed pydantic puts the input into `msg`, stop and report: the sanitization contract depends on it.

- [ ] **Step 5: Commit**

```bash
git add labbrain/schema.py tests/test_schema.py
git commit -m "feat(schema): pydantic frontmatter models for the nine note types" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Notes: parsing, links, sections and round-trip writes

**Files:**
- Create: `labbrain/notes.py`
- Test: `tests/test_notes.py`

**Interfaces:**
- Consumes: `labbrain.schema.validate_frontmatter`, `ID_FIELDS`, `FUTURE_AGENTS_HEADING`, `BaseNote`.
- Produces (`labbrain.notes`):
  - `H2_RE: re.Pattern` (group 1 = heading text), `HEADING_RE: re.Pattern`.
  - `LinkRef(target: str, line: int, field: str)` frozen dataclass with property `is_path: bool`.
  - `Note` dataclass: `path: Path`, `rel: str`, `text: str`, `data: dict | None`, `body: str`, `body_line: int`, `model: BaseNote | None`, `errors: list[str]`, `error_line: int`, `refs: list[LinkRef]`; properties `stem`, `type`; methods `get(key, default=None)`, `get_str(key) -> str | None`, `get_list(key) -> list[str]`, `get_date(key) -> date | None`.
  - `split_frontmatter(text) -> tuple[str | None, str, int]`; `parse_note_text(text, path: Path, rel: str) -> Note`; `parse_note(path, root) -> Note`.
  - `iter_body_lines(note) -> Iterator[tuple[int, str]]` (file line numbers, outside code fences); `wikilink_targets(line) -> list[str]`; `h2_headings(note) -> list[tuple[int, str]]`; `future_agents_block(note) -> list[str] | None`.
  - `safe_load(text) -> Any` (PyYAML, raises `yaml.YAMLError`); `rt_yaml() -> YAML`; `dump_frontmatter(data) -> str`; `render_note(data, body) -> str`; `atomic_write(path, text) -> None`; `update_frontmatter(path, updates: Mapping[str, Any]) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/test_notes.py` (note the four-backtick fence: the sample note contains a code fence):

````python
from __future__ import annotations

import difflib
from datetime import date
from pathlib import Path

from labbrain.notes import (
    future_agents_block,
    h2_headings,
    parse_note_text,
    update_frontmatter,
    wikilink_targets,
)

SAMPLE = """---
id: EXP-20261013-label-smoothing
type: experiment
title: "Label smoothing vs. calibration"   # keep this comment
created: 2026-10-13
updated: 2026-10-13
author: alice
status: running
tags: [calibration]
links:
  - EXP-20261001-baseline
metrics:
  - {name: ece, value: 0.04, split: val, run_id: run-002, as_of: 2026-10-13}
---
## Hypothesis

See [[EXP-20261001-baseline|the baseline]] and [[DS-20260801-main#split]].

```text
[[NOT-A-LINK]]
```

Inline `[[ALSO-NOT]]` and a table cell [[EVAL-v3\\|v3]] and ![[raw/papers/x.pdf]].
"""


def parse(text: str, rel: str = "experiments/EXP-20261013-label-smoothing.md"):
    return parse_note_text(text, Path(rel), rel)


def test_parse_sample() -> None:
    note = parse(SAMPLE)
    assert note.errors == []
    assert note.model is not None
    assert note.body_line == 15
    assert note.stem == "EXP-20261013-label-smoothing"
    assert note.type == "experiment"
    assert note.get_str("title") == "Label smoothing vs. calibration"
    assert note.get_list("tags") == ["calibration"]
    assert note.get_date("created") == date(2026, 10, 13)


def test_links_from_frontmatter_and_body() -> None:
    note = parse(SAMPLE)
    assert [(r.target, r.line, r.field) for r in note.refs] == [
        ("EXP-20261001-baseline", 1, "links"),
        ("EXP-20261001-baseline", 17, "body"),
        ("DS-20260801-main", 17, "body"),
        ("EVAL-v3", 23, "body"),
        ("raw/papers/x.pdf", 23, "body"),
    ]
    assert [r.is_path for r in note.refs] == [False, False, False, False, True]


def test_wikilink_target_forms() -> None:
    line = "[[A]] [[B|x]] [[C\\|y]] [[D#h]] [[E^b]] ![[f/g.png]] `[[H]]` [[#local]]"
    assert wikilink_targets(line) == ["A", "B", "C", "D", "E", "f/g.png"]


def test_self_links_ignored() -> None:
    text = SAMPLE.replace("Inline", "Self [[EXP-20261013-label-smoothing]] inline")
    targets = [r.target for r in parse(text).refs]
    assert "EXP-20261013-label-smoothing" not in targets


def test_missing_frontmatter() -> None:
    note = parse("# just text\n", "concepts/stray.md")
    assert note.data is None
    assert note.errors == ["missing YAML frontmatter"]


def test_invalid_yaml_reports_line_only_and_keeps_body_links() -> None:
    secret = "48151623"
    note = parse(f"---\nid: x\nmrn: [{secret}\n---\nSee [[EXP-20261001-baseline]].\n")
    assert note.data is None
    assert len(note.errors) == 1
    assert note.errors[0].startswith("frontmatter is not valid YAML (line ")
    assert secret not in note.errors[0]
    assert [r.target for r in note.refs] == ["EXP-20261001-baseline"]


def test_non_mapping_frontmatter() -> None:
    assert parse("---\n- a\n- b\n---\n").errors == ["frontmatter must be a YAML mapping"]


def test_model_failure_still_harvests_frontmatter_links() -> None:
    note = parse(SAMPLE.replace("status: running", "status: bogus"))
    assert note.model is None
    assert note.errors and note.errors[0].startswith("status:")
    assert "EXP-20261001-baseline" in [r.target for r in note.refs if r.field == "links"]


def test_h2_headings_skip_code_fences() -> None:
    assert h2_headings(parse(SAMPLE)) == [(15, "Hypothesis")]


def test_future_agents_block() -> None:
    head = "---\nid: x\n---\n"
    note = parse(head + "\n## For future agents\nline one\n\nline two\n\n## Summary\nbody\n")
    assert future_agents_block(note) == ["line one", "line two"]
    assert future_agents_block(parse(head + "## Summary\nbody\n")) is None


def test_update_frontmatter_is_a_one_line_diff(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(SAMPLE)
    assert update_frontmatter(path, {"status": "done"}) is True
    changed = [
        line
        for line in difflib.ndiff(SAMPLE.splitlines(), path.read_text().splitlines())
        if line.startswith(("+ ", "- "))
    ]
    assert changed == ["- status: running", "+ status: done"]


def test_update_frontmatter_noop_and_new_key(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(SAMPLE)
    assert update_frontmatter(path, {"status": "running"}) is False
    assert path.read_text() == SAMPLE
    assert update_frontmatter(path, {"superseded_by": "EXP-20261014-x"}) is True
    new = path.read_text()
    assert "superseded_by: EXP-20261014-x\n---\n## Hypothesis" in new
    assert new.replace("superseded_by: EXP-20261014-x\n", "") == SAMPLE


def test_update_frontmatter_writes_dates(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(SAMPLE)
    update_frontmatter(path, {"updated": date(2026, 10, 15)})
    assert "updated: 2026-10-15\n" in path.read_text()
    assert list(tmp_path.iterdir()) == [path]  # no temp files left behind
````

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_notes.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'labbrain.notes'`.

- [ ] **Step 3: Implement `labbrain/notes.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_notes.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass. If a round-trip test fails because ruamel re-formats a line of `SAMPLE` (e.g. the comment spacing), do **not** loosen the test: report the exact diff. The one-line-diff property is a spec requirement.

- [ ] **Step 5: Commit**

```bash
git add labbrain/notes.py tests/test_notes.py
git commit -m "feat(notes): parse notes, harvest links, round-trip frontmatter writes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Vault discovery, config and the note graph

**Files:**
- Create: `labbrain/vault.py`, `tests/helpers.py`
- Test: `tests/test_vault.py`

**Interfaces:**
- Consumes: `labbrain.__version__`, `labbrain.ids.DEFAULT_PREFIXES`, `labbrain.layout.CONFIG_PATH`, `labbrain.layout.iter_note_files`, `labbrain.notes.Note`, `labbrain.notes.parse_note`, `labbrain.notes.safe_load`.
- Produces (`labbrain.vault`):
  - `VaultNotFound(Exception)`, `ConfigError(Exception)`; `ENV_VAULT = "LABBRAIN_VAULT"`, `ENV_NOW = "LABBRAIN_NOW"`.
  - `now() -> datetime`, `today() -> date`.
  - `find_root(start: Path | None = None, explicit: Path | str | None = None) -> Path`.
  - `Config` (pydantic): all fields in spec section 3, with `is_agent(author) -> bool` and `author_allowed(author) -> bool`; `DEFAULT_HASH_IGNORE: list[str]`; `default_config() -> Config`; `load_config(root) -> Config`; `version_warning(config) -> str | None`.
  - `Vault` dataclass: `root: Path`, `config: Config`, `notes: dict[str, Note]` (by filename stem, first wins), `duplicates: dict[str, list[Note]]`, `by_rel: dict[str, Note]`, `inbound: dict[str, set[str]]`, `outbound: dict[str, set[str]]`; classmethod `load(root, config=None)`; methods `get(note_id)`, `all_notes()`, `of_type(note_type)`.
- Produces (`tests/helpers.py`): `MIN_CONFIG`, `make_vault(root, config=MIN_CONFIG) -> Path`, `write(root, rel, text) -> Path`, `body_for(note_type, text="Text.") -> str`, `note_text(note_id, note_type, body=None, **fields) -> str`.

- [ ] **Step 1: Create `tests/helpers.py`**

```python
"""Shared test helpers. Importable because pyproject sets pythonpath = ["tests"]."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from labbrain.notes import render_note
from labbrain.schema import DEFAULT_STATUS, REQUIRED_SECTIONS

MIN_CONFIG = "project_name: Toy\nproject_slug: toy\nlab_members: [alice, bob]\n"


def make_vault(root: Path, config: str = MIN_CONFIG) -> Path:
    (root / ".labbrain").mkdir(parents=True, exist_ok=True)
    (root / ".labbrain" / "config.yaml").write_text(config)
    return root


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def body_for(note_type: str, text: str = "Text.") -> str:
    return "".join(f"## {section}\n\n{text}\n\n" for section in REQUIRED_SECTIONS[note_type])


def note_text(note_id: str, note_type: str, body: str | None = None, **fields: Any) -> str:
    data: dict[str, Any] = {
        "id": note_id,
        "type": note_type,
        "title": fields.pop("title", note_id),
        "created": fields.pop("created", date(2026, 10, 1)),
        "updated": fields.pop("updated", date(2026, 10, 1)),
        "author": fields.pop("author", "alice"),
        "status": fields.pop("status", DEFAULT_STATUS[note_type]),
    }
    data.update(fields)
    return render_note(data, body_for(note_type) if body is None else body)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_vault.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, body_for, make_vault, note_text, write

from labbrain.vault import (
    ConfigError,
    Vault,
    VaultNotFound,
    find_root,
    load_config,
    now,
    today,
    version_warning,
)


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)


def test_find_root_walks_up(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    deep = root / "experiments" / "deep"
    deep.mkdir(parents=True)
    assert find_root(start=deep) == root.resolve()


def test_find_root_env_and_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = make_vault(tmp_path / "a")
    b = make_vault(tmp_path / "b")
    monkeypatch.setenv("LABBRAIN_VAULT", str(a))
    assert find_root(start=b) == a.resolve()
    assert find_root(start=b, explicit=b) == b.resolve()


def test_find_root_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(VaultNotFound, match="--vault"):
        find_root(start=tmp_path)
    monkeypatch.setenv("LABBRAIN_VAULT", str(tmp_path))
    with pytest.raises(VaultNotFound, match="LABBRAIN_VAULT"):
        find_root()


def test_now_honours_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABBRAIN_NOW", "2026-10-15T12:00:00")
    assert now() == datetime(2026, 10, 15, 12, 0)
    assert today() == date(2026, 10, 15)
    monkeypatch.setenv("LABBRAIN_NOW", "yesterday")
    with pytest.raises(ConfigError):
        now()


def test_config_defaults(tmp_path: Path) -> None:
    cfg = load_config(make_vault(tmp_path))
    assert cfg.min_cell_size == 11
    assert cfg.agents == ["claude", "codex", "gemini"]
    assert cfg.id_prefixes["experiment"] == "EXP"
    assert cfg.protected_data is True
    assert cfg.tracker.backend == "local"
    assert cfg.inbox_max_days == 30


def test_config_prefix_override_merges(tmp_path: Path) -> None:
    cfg = load_config(make_vault(tmp_path, MIN_CONFIG + "id_prefixes: {experiment: RUN}\n"))
    assert cfg.id_prefixes["experiment"] == "RUN"
    assert cfg.id_prefixes["claim"] == "CLM"


def test_config_errors_do_not_echo_values(tmp_path: Path) -> None:
    root = make_vault(tmp_path, MIN_CONFIG + "min_cell_size: 'x48151623'\n")
    with pytest.raises(ConfigError) as info:
        load_config(root)
    assert "min_cell_size" in str(info.value)
    assert "48151623" not in str(info.value)


@pytest.mark.parametrize("text", ["- a\n", "project_name: [oops\n"])
def test_config_must_be_a_valid_mapping(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(make_vault(tmp_path, text))


def test_authorship(tmp_path: Path) -> None:
    cfg = load_config(make_vault(tmp_path / "a"))
    assert cfg.author_allowed("alice") and cfg.author_allowed("claude")
    assert not cfg.author_allowed("mallory") and not cfg.author_allowed("")
    assert cfg.is_agent("claude") and not cfg.is_agent("alice")
    open_cfg = load_config(make_vault(tmp_path / "b", "project_name: T\nproject_slug: t\n"))
    assert open_cfg.author_allowed("mallory")


def test_version_warning(tmp_path: Path) -> None:
    assert version_warning(load_config(make_vault(tmp_path / "a"))) is None
    newer = load_config(make_vault(tmp_path / "b", MIN_CONFIG + "engine_min_version: 99.0.0\n"))
    warning = version_warning(newer)
    assert warning is not None and "99.0.0" in warning


def test_vault_graph(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "experiments/EXP-20261001-a.md", note_text("EXP-20261001-a", "experiment"))
    write(
        root,
        "concepts/topic.md",
        note_text(
            "topic",
            "concept",
            sources=["EXP-20261001-a"],
            body=body_for("concept", "See [[EXP-20261001-a]] and ![[figures/x.png]]."),
        ),
    )
    write(root, "ideas/inbox/IDEA-20261001-x.md", note_text("IDEA-20261001-x", "idea"))
    write(root, "ideas/archive/IDEA-20261001-x.md", note_text("IDEA-20261001-x", "idea"))
    write(root, "experiments/README.md", "Append-only.\n")
    vault = Vault.load(root)
    assert sorted(vault.notes) == ["EXP-20261001-a", "IDEA-20261001-x", "topic"]
    assert sorted(vault.by_rel) == [
        "concepts/topic.md",
        "experiments/EXP-20261001-a.md",
        "ideas/archive/IDEA-20261001-x.md",
        "ideas/inbox/IDEA-20261001-x.md",
    ]
    assert vault.inbound == {"EXP-20261001-a": {"topic"}}
    assert vault.outbound == {"topic": {"EXP-20261001-a"}}
    assert list(vault.duplicates) == ["IDEA-20261001-x"]
    assert len(vault.duplicates["IDEA-20261001-x"]) == 2
    assert [n.stem for n in vault.of_type("experiment")] == ["EXP-20261001-a"]
    assert vault.get("missing") is None


def test_invalid_notes_still_register_and_link(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "experiments/EXP-20261001-a.md", note_text("EXP-20261001-a", "experiment"))
    write(
        root,
        "concepts/broken.md",
        note_text("broken", "concept", status="bogus", sources=["EXP-20261001-a"]),
    )
    write(root, "concepts/unparsable.md", "---\ntitle: [oops\n---\nSee [[EXP-20261001-a]].\n")
    vault = Vault.load(root)
    assert vault.inbound["EXP-20261001-a"] == {"broken", "unparsable"}
    assert vault.notes["unparsable"].data is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_vault.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'labbrain.vault'`.

- [ ] **Step 4: Implement `labbrain/vault.py`**

```python
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


def default_config() -> Config:
    """Settings for running outside any vault (e.g. phi-scan over a code repo)."""
    return Config(project_name="(no vault)", project_slug="none")


def load_config(root: Path) -> Config:
    try:
        raw: Any = safe_load((root / CONFIG_PATH).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {CONFIG_PATH}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{CONFIG_PATH} is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{CONFIG_PATH} must be a YAML mapping")
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_vault.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add labbrain/vault.py tests/helpers.py tests/test_vault.py
git commit -m "feat(vault): discovery, config model and load-once note graph" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Valid fixture vault and test harness

**Files:**
- Create: everything under `tests/fixtures/valid/` listed below; `tests/fixtures/__init__.py`; `tests/fixtures/mutations.py`; `tests/conftest.py`
- Modify: `tests/helpers.py` (append fixture constants and git helpers)
- Test: `tests/test_fixture.py`

**Interfaces:**
- Consumes: `Vault`, `dump_frontmatter`, `rt_yaml`, `split_frontmatter`, `future_agents_block`.
- Produces (`tests/helpers.py`): `FIXTURE: Path`, `PINNED_NOW = "2026-10-15T12:00:00"`, `TODAY = date(2026, 10, 15)`, `git(cwd, *args) -> str`, `commit_all(cwd, message="fixture") -> None`.
- Produces (`tests/conftest.py`): fixture `vault_dir -> Path`: a copy of the valid vault in `tmp_path/"vault"`, `git init`ed and committed, with `LABBRAIN_NOW` and `LABBRAIN_VAULT` set.
- Produces (`tests/fixtures/mutations.py`): `Mutation(name, rule, apply, commit=True, keep_index=False)`; `MUTATIONS: list[Mutation]`; decorator `mutation(rule, *, commit=True, keep_index=False)`; `replace(vault, rel, old, new)`; path constants `BASELINE`, `SMOOTHING`, `CLAIM`, `CONCEPT`, `DECISION`, `LITERATURE`, `DATASET`, `EVAL_V1`, `EVAL_V2`, `IDEA_OPEN`, `HANDOFF`, `RAW_PAPER`.

The fixture is designed so that **every lint rule is quiet** on it. In particular: every note except ideas and handoffs has at least two distinct inbound links; every agent-authored note (author `claude`) opens with a `## For future agents` block of at most three lines; every metric-like number in an agent-authored concept or claim sits on a line with an `[[EXP-…]]` link; no text matches a PHI pattern. Write each file exactly as shown.

- [ ] **Step 1: Write the fixture configuration**

`tests/fixtures/valid/.labbrain/config.yaml`:

```yaml
project_name: Toy Image Classifier
project_slug: toy-classifier
owner: alice
lab_members: [alice, bob]
agents: [claude, codex, gemini]
modality: image
tracker: {backend: local, project: toy-classifier, runs_dir: runs}
protected_data: true
data_paths: []
min_cell_size: 11
engine_min_version: "0.1.0"
inbox_max_days: 30
```

`tests/fixtures/valid/.labbrain/phi-allow.yaml`:

```yaml
[]
```

- [ ] **Step 2: Write the protocol and dataset notes**

`tests/fixtures/valid/protocols/EVAL-v1.md`:

```markdown
---
id: EVAL-v1
type: protocol
title: "Held-out accuracy, single split"
created: 2026-08-01
updated: 2026-08-01
author: alice
status: frozen
tags: [evaluation]
links: []
version: 1
comparable_with: []
---
## Definition

Top-1 accuracy on the public test split; no class reweighting.

## Changes from previous version

First version.

## Known caveats

Single split, so variance across seeds is not captured.
```

`tests/fixtures/valid/protocols/EVAL-v2.md`:

```markdown
---
id: EVAL-v2
type: protocol
title: "AUROC and ECE on the main split"
created: 2026-08-20
updated: 2026-09-02
author: alice
status: frozen
tags: [evaluation]
links: []
version: 2
changes_from: EVAL-v1
comparable_with: []
---
## Definition

Median one-vs-rest AUROC and expected calibration error (15 bins) on the test split of [[DS-20260801-main-split]].

## Changes from previous version

Replaces accuracy with AUROC and adds calibration; numbers are not comparable with [[EVAL-v1]].

## Known caveats

ECE depends on the bin count.
```

`tests/fixtures/valid/datasets/DS-20260801-main-split.md`:

```markdown
---
id: DS-20260801-main-split
type: dataset
title: "Public benchmark, main split"
created: 2026-08-01
updated: 2026-08-01
author: bob
status: active
tags: []
links: []
location: "s3://toy-bucket/benchmark/v1/"
extracted: 2026-08-01
counts: {train_images: 50000, test_images: 10000}
protected: false
---
## Source

A public image classification benchmark, downloaded unchanged.

## Inclusion and exclusion

All images; no filtering.

## Split definition

The benchmark's official train and test split.

## Known issues

None recorded as of 2026-08-01.
```

- [ ] **Step 3: Write the experiment notes**

`tests/fixtures/valid/experiments/README.md`:

```markdown
Append-only: add sections, never rewrite existing fields except status and superseded_by.
```

`tests/fixtures/valid/experiments/EXP-20260901-baseline.md`:

```markdown
---
id: EXP-20260901-baseline
type: experiment
title: "Baseline classifier"
created: 2026-09-01
updated: 2026-09-02
author: alice
status: done
tags: [baseline]
links: []
hypothesis: "A plain ResNet reaches a usable AUROC on the main split"
protocol: EVAL-v2
tracker: {backend: local, run_ids: [run-001]}
code: {repo: "../toy-model", sha: "1a2b3c4", dirty: false}
config_hash: "sha256:3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b"
dataset: DS-20260801-main-split
metrics:
  - {name: auroc_median, value: 0.81, split: test, run_id: run-001, as_of: 2026-09-02}
---
## Hypothesis

A plain ResNet reaches a usable AUROC on the main split.

## Setup

Default training recipe; no parent experiment.

## Results

| metric | value | run |
|---|---|---|
| auroc_median | 0.81 | run-001 |

## Interpretation

(human) Good enough to serve as the comparison point.

## Next

Try label smoothing.
```

`tests/fixtures/valid/experiments/EXP-20260910-label-smoothing.md`:

```markdown
---
id: EXP-20260910-label-smoothing
type: experiment
title: "Label smoothing vs. calibration"
created: 2026-09-10
updated: 2026-09-12
author: claude
status: done
tags: [calibration]
links: [EXP-20260901-baseline]
hypothesis: "Label smoothing improves calibration without lowering AUROC"
protocol: EVAL-v2
tracker: {backend: local, run_ids: [run-002]}
code: {repo: "../toy-model", sha: "5e6f7a8", dirty: false}
config_hash: "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
dataset: DS-20260801-main-split
metrics:
  - {name: auroc_median, value: 0.81, split: test, run_id: run-002, as_of: 2026-09-12}
  - {name: ece, value: 0.04, split: test, run_id: run-002, as_of: 2026-09-12}
---
## For future agents

One run comparing label smoothing against [[EXP-20260901-baseline]] under EVAL-v2.
Safe to rely on the metrics block; check the protocol before comparing elsewhere.

## Hypothesis

Label smoothing improves calibration without lowering AUROC.

## Setup

Diff vs. [[EXP-20260901-baseline]]: `train.label_smoothing` set to a small positive value.

## Results

| metric | value | run |
|---|---|---|
| auroc_median | 0.81 | run-002 |
| ece | 0.04 | run-002 |

## Interpretation

(agent interpretation, unreviewed) Calibration improved at no AUROC cost.

## Next

Check whether the effect holds at other smoothing values.
```

- [ ] **Step 4: Write the claim, concept, decision and literature notes**

`tests/fixtures/valid/claims/CLM-20261001-median-auroc.md`:

```markdown
---
id: CLM-20261001-median-auroc
type: claim
title: "Median AUROC of the baseline"
created: 2026-10-01
updated: 2026-10-01
author: claude
status: supported
tags: [results]
links: []
statement: "Median AUROC on the held-out test split is 0.81"
value: 0.81
value_format: "{:.2f}"
tolerance: 0.005
evidence: [EXP-20260901-baseline]
protocol: EVAL-v2
manuscript_locations: ["manuscripts/main.md#results"]
---
## For future agents

Registers the headline median AUROC quoted in the results section.
Backed by [[EXP-20260901-baseline]] under EVAL-v2; re-check if that experiment is superseded.

## Evidence summary

Median AUROC 0.81 on the test split, from [[EXP-20260901-baseline]] (run-001).

## History

- 2026-10-01: created with value 0.81 (supported).
```

`tests/fixtures/valid/concepts/label-smoothing-calibration.md`:

```markdown
---
id: label-smoothing-calibration
type: concept
title: "Label smoothing and calibration"
created: 2026-09-15
updated: 2026-10-01
author: claude
status: active
tags: [calibration]
links: [CLM-20261001-median-auroc]
sources: [EXP-20260910-label-smoothing, LIT-szegedy2016-rethinking]
---
## For future agents

Synthesis of what this project knows about label smoothing and calibration.
Numbers here are copied from linked experiments; trust the experiment notes over this page.

## Summary

Label smoothing regularises over-confident logits, which tends to improve calibration.

## Evidence

ECE fell to 0.04 at unchanged AUROC in [[EXP-20260910-label-smoothing]], as of 2026-09-12.

## Open questions

Does the effect survive a protocol change such as [[EVAL-v1]] to [[EVAL-v2]]?

## Related

[[ADR-20260905-adopt-eval-v2]] · [[LIT-szegedy2016-rethinking]]
```

`tests/fixtures/valid/decisions/ADR-20260905-adopt-eval-v2.md`:

```markdown
---
id: ADR-20260905-adopt-eval-v2
type: decision
title: "Adopt EVAL-v2 for all new experiments"
created: 2026-09-05
updated: 2026-09-05
author: alice
status: accepted
tags: [evaluation]
links: [EVAL-v2]
---
## Context

Accuracy under EVAL-v1 hid calibration problems; see [[label-smoothing-calibration]] and [[LIT-szegedy2016-rethinking]].

## Decision

New experiments use [[EVAL-v2]].

## Alternatives considered

Keeping accuracy as the headline metric.

## Consequences

Numbers under EVAL-v1 and EVAL-v2 are not compared directly.
```

`tests/fixtures/valid/literature/LIT-szegedy2016-rethinking.md`:

```markdown
---
id: LIT-szegedy2016-rethinking
type: literature
title: "Rethinking the Inception Architecture for Computer Vision"
created: 2026-09-14
updated: 2026-09-14
author: bob
status: active
tags: [regularisation]
links: []
year: 2016
venue: CVPR
relevance: high
url: "https://arxiv.org/abs/1512.00567"
---
## Summary

Introduces label smoothing as a regulariser for classification.

## Methods worth borrowing

Label smoothing with a small epsilon.

## Results to compare against

ImageNet top-1 error under the paper's own evaluation; not comparable with EVAL-v2.

## Style notes

Short ablation tables with one change per row.
```

- [ ] **Step 5: Write the ideas, handoff, raw file and log**

`tests/fixtures/valid/ideas/inbox/IDEA-20261010-smoothing-schedule.md`:

```markdown
---
id: IDEA-20261010-smoothing-schedule
type: idea
title: "Anneal label smoothing over training"
created: 2026-10-10
updated: 2026-10-10
author: bob
status: open
tags: [calibration]
links: []
---
Anneal the smoothing value to zero over training and see whether late-epoch calibration holds.
```

`tests/fixtures/valid/ideas/archive/IDEA-20260912-smoothing-helps.md`:

```markdown
---
id: IDEA-20260912-smoothing-helps
type: idea
title: "Label smoothing might fix over-confidence"
created: 2026-09-12
updated: 2026-09-15
author: alice
status: consolidated
tags: [calibration]
links: []
consolidated_into: label-smoothing-calibration
---
Over-confident logits on the baseline might be tamed by label smoothing.
```

`tests/fixtures/valid/handoffs/HO-20261014-1420-claude.md`:

```markdown
---
id: HO-20261014-1420-claude
type: handoff
title: "Registered the headline AUROC claim"
created: 2026-10-14
updated: 2026-10-14
author: claude
status: final
tags: []
links: []
agent: claude
session_goal: "Register the headline AUROC as a claim"
files_touched: [claims/CLM-20261001-median-auroc.md]
---
## For future agents

Session handoff; the claim and decision it mentions are the durable record.

## Done

Checked [[CLM-20261001-median-auroc]] against [[EXP-20260901-baseline]] and [[EXP-20260910-label-smoothing]].

## In progress

Nothing.

## Blockers

None.

## Next step for whoever picks this up

Re-read [[ADR-20260905-adopt-eval-v2]] before adding new experiments.
```

`tests/fixtures/valid/raw/papers/szegedy2016-rethinking.txt`:

```text
Placeholder for the paper text; the PDF is not stored in this fixture.
```

`tests/fixtures/valid/log/2026-10-14.md`:

```markdown
- 14:20 [claude] handoff: wrote HO-20261014-1420-claude
```

- [ ] **Step 6: Extend `tests/helpers.py`**

Append:

```python
import shutil  # noqa: E402  (grouped with the fixture helpers below)
import subprocess  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "valid"
PINNED_NOW = "2026-10-15T12:00:00"
TODAY = date(2026, 10, 15)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def commit_all(cwd: Path, message: str = "fixture") -> None:
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "--allow-empty", "-m", message)


def copy_fixture(dest: Path) -> Path:
    shutil.copytree(FIXTURE, dest)
    return dest
```

Then move the `import shutil` and `import subprocess` lines to the top import block and delete the `noqa` comments (`uv run ruff check --fix tests/helpers.py` does this).

- [ ] **Step 7: Create `tests/conftest.py`, `tests/fixtures/__init__.py` and `tests/fixtures/mutations.py`**

`tests/conftest.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from helpers import PINNED_NOW, commit_all, copy_fixture, git


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A committed git copy of the valid fixture, with time and vault pinned."""
    dest = copy_fixture(tmp_path / "vault")
    git(dest, "init", "-q", "-b", "main")
    commit_all(dest, "valid fixture")
    monkeypatch.setenv("LABBRAIN_NOW", PINNED_NOW)
    monkeypatch.setenv("LABBRAIN_VAULT", str(dest))
    return dest
```

`tests/fixtures/__init__.py`: empty file.

`tests/fixtures/mutations.py`:

```python
"""Named mutations of the valid fixture, one or more per lint rule.

Each mutation changes the vault so that exactly its declared rule fires. Its
docstring says why no other rule fires; reviewers check that claim. Harness
(tests/test_gate.py): index.md is deleted unless keep_index; the mutation is
committed unless commit=False (only frozen-edit mutations stay uncommitted).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

BASELINE = "experiments/EXP-20260901-baseline.md"
SMOOTHING = "experiments/EXP-20260910-label-smoothing.md"
CLAIM = "claims/CLM-20261001-median-auroc.md"
CONCEPT = "concepts/label-smoothing-calibration.md"
DECISION = "decisions/ADR-20260905-adopt-eval-v2.md"
LITERATURE = "literature/LIT-szegedy2016-rethinking.md"
DATASET = "datasets/DS-20260801-main-split.md"
EVAL_V1 = "protocols/EVAL-v1.md"
EVAL_V2 = "protocols/EVAL-v2.md"
IDEA_OPEN = "ideas/inbox/IDEA-20261010-smoothing-schedule.md"
HANDOFF = "handoffs/HO-20261014-1420-claude.md"
RAW_PAPER = "raw/papers/szegedy2016-rethinking.txt"


@dataclass(frozen=True)
class Mutation:
    name: str
    rule: str
    apply: Callable[[Path], None]
    commit: bool = True
    keep_index: bool = False


MUTATIONS: list[Mutation] = []


def mutation(
    rule: str, *, commit: bool = True, keep_index: bool = False
) -> Callable[[Callable[[Path], None]], Callable[[Path], None]]:
    def register(fn: Callable[[Path], None]) -> Callable[[Path], None]:
        MUTATIONS.append(Mutation(fn.__name__, rule, fn, commit, keep_index))
        return fn

    return register


def replace(vault: Path, rel: str, old: str, new: str) -> None:
    path = vault / rel
    text = path.read_text()
    assert text.count(old) == 1, f"{rel}: expected exactly one occurrence of {old!r}"
    path.write_text(text.replace(old, new))
```

- [ ] **Step 8: Write the fixture tests**

`tests/test_fixture.py`:

```python
from __future__ import annotations

from pathlib import Path

from helpers import FIXTURE, git

from labbrain.notes import dump_frontmatter, future_agents_block, rt_yaml, split_frontmatter
from labbrain.vault import Vault

EXPECTED = {
    "EXP-20260901-baseline",
    "EXP-20260910-label-smoothing",
    "EVAL-v1",
    "EVAL-v2",
    "DS-20260801-main-split",
    "CLM-20261001-median-auroc",
    "label-smoothing-calibration",
    "ADR-20260905-adopt-eval-v2",
    "LIT-szegedy2016-rethinking",
    "IDEA-20261010-smoothing-schedule",
    "IDEA-20260912-smoothing-helps",
    "HO-20261014-1420-claude",
}


def test_fixture_notes_parse_cleanly() -> None:
    vault = Vault.load(FIXTURE)
    assert set(vault.notes) == EXPECTED
    assert vault.duplicates == {}
    for note in vault.all_notes():
        assert note.errors == [], note.rel


def test_every_linkable_note_has_two_inbound_links() -> None:
    """Harness invariant: a mutation that removes one link never creates an orphan."""
    vault = Vault.load(FIXTURE)
    for stem, note in vault.notes.items():
        if note.type not in ("idea", "handoff"):
            assert len(vault.inbound.get(stem, set())) >= 2, stem


def test_agent_notes_open_with_future_agents_block() -> None:
    vault = Vault.load(FIXTURE)
    for note in vault.all_notes():
        if note.get_str("author") == "claude":
            block = future_agents_block(note)
            assert block and len(block) <= 3, note.rel


def test_fixture_frontmatter_round_trips_byte_for_byte() -> None:
    for path in sorted(FIXTURE.rglob("*.md")):
        fm, _, _ = split_frontmatter(path.read_text())
        if fm is not None:
            assert dump_frontmatter(rt_yaml().load(fm)) == fm, path.name


def test_vault_dir_is_a_clean_git_copy(vault_dir: Path) -> None:
    assert (vault_dir / ".git").is_dir()
    assert git(vault_dir, "status", "--porcelain") == ""
```

- [ ] **Step 9: Run tests**

Run: `uv run pytest tests/test_fixture.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass. If the round-trip test fails for a fixture file, change **that fixture line** to ruamel's output (print `dump_frontmatter(rt_yaml().load(fm))` to see it) and note the change in the commit message. Do not change `rt_yaml()` settings.

- [ ] **Step 10: Commit**

```bash
git add tests
git commit -m "test: valid fixture vault, git harness and mutation registry" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Lint framework, `schema` and `missing-section` rules, single-file `validate`

**Files:**
- Create: `labbrain/lint/__init__.py`, `labbrain/lint/rules/__init__.py`, `labbrain/lint/rules/schema_rules.py`, `labbrain/validate.py`
- Modify: `tests/fixtures/mutations.py` (append)
- Test: `tests/test_schema_rules.py`, `tests/test_validate.py`, `tests/test_gate.py`

**Interfaces:**
- Consumes: `Vault`, `Config`, `today`, `Note`, `parse_note`, `h2_headings`, `future_agents_block`, `is_valid_id`, `REQUIRED_SECTIONS`, `FUTURE_AGENTS_HEADING`, `Finding`, `sort_findings`, `is_note_rel`, `iter_note_files`, `find_root`, `load_config`, `VaultNotFound`.
- Produces (`labbrain.lint`): `LintContext(vault, today, base="HEAD", cache={})`; `Rule(name, severity, description, fn)`; `RULES: dict[str, Rule]`; decorator `rule(name, severity, description)`; `load_rules() -> dict[str, Rule]` (imports every module in `labbrain.lint.rules`); `UnknownRuleError(ValueError)`; `run(vault, *, today=None, base="HEAD", only=None) -> list[Finding]` (sorted).
- Produces (`labbrain.lint.rules.schema_rules`): `check_note(note, config) -> list[Finding]` (rules `schema` and `missing-section` for one note); rules `schema`, `missing-section`.
- Produces (`labbrain.validate`): `validate_path(path, *, vault=None) -> list[Finding]`; `validate_paths(paths, *, vault=None) -> list[Finding]`. Findings about the call itself use rule `validate`.
- Every later rule module follows this pattern: `from labbrain.lint import LintContext, rule`, then `@rule("<name>", <SEVERITY>, "<description>")` on a generator `def ...(ctx: LintContext) -> Iterator[Finding]`.

- [ ] **Step 1: Write the failing unit tests**

`tests/test_schema_rules.py`:

```python
from __future__ import annotations

from pathlib import Path

from helpers import body_for, make_vault, note_text, write

from labbrain.lint.rules.schema_rules import check_note
from labbrain.notes import parse_note
from labbrain.vault import load_config

REL = "decisions/ADR-20261001-x.md"


def check(root: Path, rel: str = REL) -> list[tuple[str, str, str]]:
    note = parse_note(root / rel, root)
    return [(f.rule, f.severity, f.message) for f in check_note(note, load_config(root))]


def test_valid_note_has_no_findings(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-x", "decision"))
    assert check(root) == []


def test_id_must_match_filename(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-y", "decision"))
    assert check(root) == [("schema", "error", "id does not match the filename")]


def test_filename_must_be_a_valid_id(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "decisions/adr-one.md", note_text("adr-one", "decision"))
    assert check(root, "decisions/adr-one.md") == [
        ("schema", "error", "filename is not a valid decision ID")
    ]


def test_author_must_be_member_or_agent(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-x", "decision", author="mallory"))
    assert check(root) == [("schema", "error", "author is not in lab_members or agents")]


def test_model_errors_are_schema_errors(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-x", "decision", status="bogus"))
    findings = check(root)
    assert len(findings) == 1
    assert findings[0][:2] == ("schema", "error")
    assert findings[0][2].startswith("status:")


def test_missing_section(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    body = body_for("decision").replace("## Consequences\n\nText.\n\n", "")
    write(root, REL, note_text("ADR-20261001-x", "decision", body=body))
    assert check(root) == [
        ("missing-section", "warning", "missing required section: ## Consequences")
    ]


def test_agent_note_needs_future_agents_block(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, REL, note_text("ADR-20261001-x", "decision", author="claude"))
    assert check(root) == [
        (
            "missing-section",
            "warning",
            "agent-authored note must start with '## For future agents'",
        )
    ]


def test_agent_block_at_most_three_lines(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    four = "## For future agents\n\na\nb\nc\nd\n\n" + body_for("decision")
    write(root, REL, note_text("ADR-20261001-x", "decision", author="claude", body=four))
    assert check(root) == [
        ("missing-section", "warning", "'## For future agents' block has more than 3 lines")
    ]
    three = "## For future agents\n\na\nb\nc\n\n" + body_for("decision")
    write(root, REL, note_text("ADR-20261001-x", "decision", author="claude", body=three))
    assert check(root) == []


def test_stray_file_without_frontmatter(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "concepts/stray.md", "just text\n")
    assert check(root, "concepts/stray.md") == [("schema", "error", "missing YAML frontmatter")]
```

`tests/test_validate.py`:

```python
from __future__ import annotations

import shutil
from pathlib import Path

from fixtures.mutations import CONCEPT, IDEA_OPEN, replace

from labbrain.layout import is_note_rel
from labbrain.validate import validate_path, validate_paths


def note_paths(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.md") if is_note_rel(p.relative_to(root).as_posix())]


def test_fixture_notes_validate_clean(vault_dir: Path) -> None:
    assert validate_paths(note_paths(vault_dir)) == []


def test_non_note_files_get_no_schema_check(vault_dir: Path) -> None:
    paths = [vault_dir / "experiments" / "README.md", vault_dir / "log" / "2026-10-14.md"]
    assert validate_paths(paths) == []


def test_outside_vault_is_info(vault_dir: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.md"
    other.write_text("x\n")
    assert [(f.rule, f.severity) for f in validate_path(other)] == [("validate", "info")]


def test_missing_file_is_an_error(vault_dir: Path) -> None:
    findings = validate_path(vault_dir / "experiments" / "EXP-20990101-none.md")
    assert [(f.rule, f.severity) for f in findings] == [("validate", "error")]


def test_duplicate_detected_without_loading_vault(vault_dir: Path) -> None:
    src = vault_dir / IDEA_OPEN
    shutil.copy(src, vault_dir / "ideas" / "archive" / src.name)
    findings = validate_path(src)
    assert [(f.rule, f.message.split(";")[0]) for f in findings] == [
        ("schema", "duplicate ID IDEA-20261010-smoothing-schedule")
    ]


def test_broken_note_reports_schema_error(vault_dir: Path) -> None:
    replace(vault_dir, CONCEPT, "status: active", "status: archived")
    findings = validate_path(vault_dir / CONCEPT)
    assert [(f.rule, f.severity) for f in findings] == [("schema", "error")]
```

- [ ] **Step 2: Write the gate test and the first mutations**

`tests/test_gate.py`:

```python
"""M2 gate: the valid fixture is clean, and each mutation fires exactly its rule."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.mutations import MUTATIONS, Mutation
from helpers import TODAY, commit_all

from labbrain import lint
from labbrain.findings import Finding
from labbrain.vault import Vault


def run_lint(vault_dir: Path) -> list[Finding]:
    return lint.run(Vault.load(vault_dir), today=TODAY)


def test_valid_fixture_has_no_findings(vault_dir: Path) -> None:
    findings = run_lint(vault_dir)
    assert findings == [], [f.to_dict() for f in findings]


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda m: m.name)
def test_mutation_triggers_exactly_its_rule(vault_dir: Path, mutation: Mutation) -> None:
    mutation.apply(vault_dir)
    if not mutation.keep_index:
        (vault_dir / "index.md").unlink(missing_ok=True)
    if mutation.commit:
        commit_all(vault_dir, mutation.name)
    findings = run_lint(vault_dir)
    assert {f.rule for f in findings} == {mutation.rule}, [f.to_dict() for f in findings]
```

Append to `tests/fixtures/mutations.py`:

```python
# --- schema -----------------------------------------------------------------


@mutation("schema")
def schema_bad_status(vault: Path) -> None:
    """Concept status outside its enum. Sections, sources and links are untouched."""
    replace(vault, CONCEPT, "status: active", "status: archived")


@mutation("schema")
def schema_id_mismatch(vault: Path) -> None:
    """`id` disagrees with the filename. Notes are keyed by filename, so links still resolve."""
    replace(vault, LITERATURE, "id: LIT-szegedy2016-rethinking", "id: LIT-szegedy2016-other")


@mutation("schema")
def schema_unknown_author(vault: Path) -> None:
    """Decision author outside lab_members and agents; a human author needs no agent block."""
    replace(vault, DECISION, "author: alice", "author: mallory")


@mutation("schema")
def schema_done_without_dataset(vault: Path) -> None:
    """Done experiment loses `dataset`. The dataset keeps two other inbound links."""
    replace(vault, BASELINE, "dataset: DS-20260801-main-split\n", "")


@mutation("schema")
def schema_invalid_yaml(vault: Path) -> None:
    """Literature frontmatter stops parsing. It has no ID-bearing fields, so no links
    are lost, and links to it still resolve by filename."""
    replace(vault, LITERATURE, "venue: CVPR", "venue: [CVPR")


@mutation("schema")
def schema_stray_file(vault: Path) -> None:
    """Markdown without frontmatter in a note folder. It has no type, so no other rule
    inspects it, and its text matches no PHI pattern."""
    (vault / "concepts" / "scratch-notes.md").write_text("just some text\n")


@mutation("schema")
def schema_duplicate_id(vault: Path) -> None:
    """Same idea filename in inbox and archive. Ideas are exempt from orphan and the
    copy is as recent as the original."""
    src = vault / IDEA_OPEN
    (vault / "ideas" / "archive" / src.name).write_text(src.read_text())


# --- missing-section ----------------------------------------------------------


@mutation("missing-section")
def missing_required_section(vault: Path) -> None:
    """EVAL-v1 loses its `## Known caveats` heading; the paragraph stays."""
    replace(vault, EVAL_V1, "## Known caveats\n\n", "")


@mutation("missing-section")
def missing_future_agents_block(vault: Path) -> None:
    """The agent-authored concept loses its leading block. undated-fact skips that
    block anyway, and the remaining lines are unchanged."""
    replace(
        vault,
        CONCEPT,
        "## For future agents\n\n"
        "Synthesis of what this project knows about label smoothing and calibration.\n"
        "Numbers here are copied from linked experiments; "
        "trust the experiment notes over this page.\n\n",
        "",
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_schema_rules.py tests/test_validate.py tests/test_gate.py -v`
Expected: collection errors, `ModuleNotFoundError: No module named 'labbrain.lint'`.

- [ ] **Step 4: Implement `labbrain/lint/__init__.py` and `labbrain/lint/rules/__init__.py`**

`labbrain/lint/__init__.py`:

```python
"""Lint registry and runner.

Rules live in ``labbrain.lint.rules.*`` and register themselves with
``@rule``. Every rule is a pure function of a ``LintContext``; rule modules
are discovered automatically, so adding a rule never touches this file.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from labbrain.findings import Finding, sort_findings
from labbrain.vault import Vault
from labbrain.vault import today as _today


@dataclass
class LintContext:
    vault: Vault
    today: date
    base: str = "HEAD"
    cache: dict[str, Any] = field(default_factory=dict)


RuleFn = Callable[[LintContext], Iterable[Finding]]


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str
    description: str
    fn: RuleFn


RULES: dict[str, Rule] = {}


class UnknownRuleError(ValueError):
    """--rule named a rule that does not exist."""


def rule(name: str, severity: str, description: str) -> Callable[[RuleFn], RuleFn]:
    def register(fn: RuleFn) -> RuleFn:
        existing = RULES.get(name)
        if existing is not None and existing.fn is not fn:
            raise ValueError(f"duplicate lint rule: {name}")
        RULES[name] = Rule(name, severity, description, fn)
        return fn

    return register


_loaded = False


def load_rules() -> dict[str, Rule]:
    global _loaded
    if not _loaded:
        from labbrain.lint import rules as package

        for info in pkgutil.iter_modules(package.__path__):
            importlib.import_module(f"{package.__name__}.{info.name}")
        _loaded = True
    return RULES


def run(
    vault: Vault,
    *,
    today: date | None = None,
    base: str = "HEAD",
    only: Iterable[str] | None = None,
) -> list[Finding]:
    rules = load_rules()
    selected = set(only) if only else None
    if selected is not None and selected - set(rules):
        unknown = ", ".join(sorted(selected - set(rules)))
        raise UnknownRuleError(f"unknown lint rule(s): {unknown}")
    ctx = LintContext(vault=vault, today=today or _today(), base=base)
    findings: list[Finding] = []
    for name in sorted(rules):
        if selected is None or name in selected:
            findings.extend(rules[name].fn(ctx))
    return sort_findings(findings)
```

`labbrain/lint/rules/__init__.py`:

```python
"""Lint rule modules. Each module registers its rules with @labbrain.lint.rule."""
```

- [ ] **Step 5: Implement `labbrain/lint/rules/schema_rules.py`**

```python
"""schema and missing-section: single-note checks shared with `labbrain validate`."""

from __future__ import annotations

from collections.abc import Iterator

from labbrain.findings import ERROR, WARNING, Finding
from labbrain.ids import is_valid_id
from labbrain.lint import LintContext, rule
from labbrain.notes import Note, future_agents_block, h2_headings
from labbrain.schema import FUTURE_AGENTS_HEADING, REQUIRED_SECTIONS
from labbrain.vault import Config

MAX_FUTURE_AGENTS_LINES = 3


def schema_findings(note: Note, config: Config) -> list[Finding]:
    out = [Finding(note.rel, note.error_line, "schema", ERROR, msg) for msg in note.errors]
    if note.data is None:
        return out
    raw_id = note.data.get("id")
    if isinstance(raw_id, str) and raw_id != note.stem:
        out.append(Finding(note.rel, 1, "schema", ERROR, "id does not match the filename"))
    note_type = note.type
    if note_type in REQUIRED_SECTIONS and not is_valid_id(
        note.stem, note_type, config.id_prefixes
    ):
        out.append(
            Finding(note.rel, 1, "schema", ERROR, f"filename is not a valid {note_type} ID")
        )
    author = note.data.get("author")
    if isinstance(author, str) and not config.author_allowed(author):
        out.append(
            Finding(note.rel, 1, "schema", ERROR, "author is not in lab_members or agents")
        )
    return out


def section_findings(note: Note, config: Config) -> list[Finding]:
    if note.data is None or note.type not in REQUIRED_SECTIONS:
        return []
    out = []
    present = {title for _, title in h2_headings(note)}
    for section in REQUIRED_SECTIONS[note.type]:
        if section not in present:
            out.append(
                Finding(
                    note.rel,
                    note.body_line,
                    "missing-section",
                    WARNING,
                    f"missing required section: ## {section}",
                )
            )
    if config.is_agent(note.get_str("author")):
        block = future_agents_block(note)
        if block is None:
            message = f"agent-authored note must start with '## {FUTURE_AGENTS_HEADING}'"
        elif len(block) > MAX_FUTURE_AGENTS_LINES:
            message = (
                f"'## {FUTURE_AGENTS_HEADING}' block has more than "
                f"{MAX_FUTURE_AGENTS_LINES} lines"
            )
        else:
            message = ""
        if message:
            out.append(Finding(note.rel, note.body_line, "missing-section", WARNING, message))
    return out


def check_note(note: Note, config: Config) -> list[Finding]:
    """All single-note checks: what `validate` runs on one file."""
    return schema_findings(note, config) + section_findings(note, config)


def _per_note(ctx: LintContext) -> list[Finding]:
    if "note_checks" not in ctx.cache:
        config = ctx.vault.config
        ctx.cache["note_checks"] = [
            f for note in ctx.vault.all_notes() for f in check_note(note, config)
        ]
    return ctx.cache["note_checks"]


@rule("schema", ERROR, "Frontmatter model, ID format, id = filename, author, duplicate IDs")
def schema_rule(ctx: LintContext) -> Iterator[Finding]:
    yield from (f for f in _per_note(ctx) if f.rule == "schema")
    for stem, group in ctx.vault.duplicates.items():
        for note in group:
            others = ", ".join(n.rel for n in group if n is not note)
            yield Finding(note.rel, 1, "schema", ERROR, f"duplicate ID {stem}; also at {others}")


@rule("missing-section", WARNING, "Required H2 sections; For-future-agents block on agent notes")
def missing_section_rule(ctx: LintContext) -> Iterator[Finding]:
    yield from (f for f in _per_note(ctx) if f.rule == "missing-section")
```

- [ ] **Step 6: Implement `labbrain/validate.py`**

```python
"""Single-file validation: what the M5 PostToolUse hook runs on every write.

Never loads the whole vault. It parses one note, checks it against the config,
and finds duplicate filenames with a directory walk.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from labbrain.findings import ERROR, INFO, Finding, sort_findings
from labbrain.layout import is_note_rel, iter_note_files
from labbrain.notes import parse_note
from labbrain.vault import Config, VaultNotFound, find_root, load_config

RULE = "validate"


def validate_path(path: Path, *, vault: Path | None = None) -> list[Finding]:
    target = path.expanduser().resolve()
    try:
        root = find_root(start=target.parent, explicit=vault)
    except VaultNotFound:
        return [Finding(target.name, 0, RULE, INFO, "not inside a vault; skipped")]
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        return [Finding(target.name, 0, RULE, INFO, "outside the vault; skipped")]
    if not target.is_file():
        return [Finding(rel, 0, RULE, ERROR, "file does not exist")]
    config = load_config(root)
    findings: list[Finding] = []
    if is_note_rel(rel):
        findings.extend(_check_note_file(target, root, config))
    return sort_findings(findings)


def _check_note_file(target: Path, root: Path, config: Config) -> list[Finding]:
    from labbrain.lint.rules.schema_rules import check_note

    note = parse_note(target, root)
    findings = check_note(note, config)
    for other in iter_note_files(root):
        if other.stem == target.stem and other.resolve() != target:
            where = other.relative_to(root).as_posix()
            findings.append(
                Finding(note.rel, 1, "schema", ERROR, f"duplicate ID {target.stem}; also at {where}")
            )
    return findings


def validate_paths(paths: Iterable[Path], *, vault: Path | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        findings.extend(validate_path(path, vault=vault))
    return sort_findings(findings)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema_rules.py tests/test_validate.py tests/test_gate.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, including 9 parametrized gate cases plus `test_valid_fixture_has_no_findings`.

- [ ] **Step 8: Commit**

```bash
git add labbrain/lint labbrain/validate.py tests
git commit -m "feat(lint): rule registry, schema and missing-section rules, validate" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `broken-link` and `orphan`

**Files:**
- Create: `labbrain/lint/rules/link_rules.py`
- Modify: `tests/fixtures/mutations.py` (append)
- Test: `tests/test_link_rules.py`

**Interfaces:**
- Consumes: `LintContext`, `rule`, `Vault.notes`, `Vault.inbound`, `Vault.all_notes()`, `Note.refs`, `LinkRef.is_path`.
- Produces: rules `broken-link` (error) and `orphan` (warning). `ORPHAN_EXEMPT = frozenset({"idea", "handoff"})`.

- [ ] **Step 1: Write the failing tests**

`tests/test_link_rules.py`:

```python
from __future__ import annotations

from pathlib import Path

from helpers import TODAY, body_for, make_vault, note_text, write

from labbrain import lint
from labbrain.vault import Vault


def rules_fired(root: Path, *names: str) -> list[tuple[str, str, str]]:
    findings = lint.run(Vault.load(root), today=TODAY, only=names)
    return [(f.rule, f.path, f.message) for f in findings]


def test_path_targets_resolve_against_the_filesystem(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    body = body_for("decision", "![[figures/roc.png]] ![[pr.png]] ![[figures/missing.png]]")
    write(root, "decisions/ADR-20261001-x.md", note_text("ADR-20261001-x", "decision", body=body))
    write(root, "figures/roc.png", "png")
    write(root, "raw/plots/pr.png", "png")
    found = rules_fired(root, "broken-link")
    assert {f[2] for f in found} == {"body: missing file figures/missing.png"}


def test_unresolved_ids_in_body_and_frontmatter(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    body = body_for("decision", "See [[EXP-20990101-nowhere]].")
    write(
        root,
        "decisions/ADR-20261001-x.md",
        note_text("ADR-20261001-x", "decision", links=["EVAL-v9"], body=body),
    )
    messages = {f[2] for f in rules_fired(root, "broken-link")}
    assert messages == {
        "links: unresolved link [[EVAL-v9]]",
        "body: unresolved link [[EXP-20990101-nowhere]]",
    }


def test_orphans_and_exemptions(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "decisions/ADR-20261001-a.md", note_text("ADR-20261001-a", "decision"))
    write(
        root,
        "decisions/ADR-20261001-b.md",
        note_text("ADR-20261001-b", "decision", links=["ADR-20261001-a"]),
    )
    write(root, "ideas/inbox/IDEA-20261001-c.md", note_text("IDEA-20261001-c", "idea", body="x\n"))
    write(root, "concepts/stray.md", "no frontmatter\n")
    assert rules_fired(root, "orphan") == [
        ("orphan", "decisions/ADR-20261001-b.md", "no inbound links")
    ]
```

Append to `tests/fixtures/mutations.py`:

```python
# --- broken-link / orphan ------------------------------------------------------

ORPHAN_LITERATURE = """---
id: LIT-doe2020-calibration
type: literature
title: "A study of calibration"
created: 2026-10-02
updated: 2026-10-02
author: bob
status: active
tags: []
links: []
year: 2020
relevance: low
---
## Summary

A survey of calibration metrics.

## Methods worth borrowing

Reliability diagrams.

## Results to compare against

None under our protocols.

## Style notes

Clear figures.
"""


@mutation("broken-link")
def broken_body_link(vault: Path) -> None:
    """Concept links to an ID that does not exist; the line carries no number."""
    replace(
        vault,
        CONCEPT,
        "[[ADR-20260905-adopt-eval-v2]] · [[LIT-szegedy2016-rethinking]]",
        "[[ADR-20260905-adopt-eval-v2]] · [[LIT-szegedy2016-rethinking]] · [[EXP-20990101-nowhere]]",
    )


@mutation("broken-link")
def broken_frontmatter_link(vault: Path) -> None:
    """Decision `links` names a missing protocol; EVAL-v2 keeps its other inbound links."""
    replace(vault, DECISION, "links: [EVAL-v2]", "links: [EVAL-v2, EVAL-v9]")


@mutation("broken-link")
def broken_embed(vault: Path) -> None:
    """Experiment embeds a figure that does not exist; path targets never touch the ID graph."""
    replace(vault, BASELINE, "## Next\n", "## Next\n\n![[figures/roc.png]]\n")


@mutation("orphan")
def orphan_new_literature(vault: Path) -> None:
    """A complete, valid literature note that nothing links to."""
    (vault / "literature" / "LIT-doe2020-calibration.md").write_text(ORPHAN_LITERATURE)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_link_rules.py tests/test_gate.py -v`
Expected: `test_link_rules.py` fails with `UnknownRuleError: unknown lint rule(s): broken-link`; the four new gate cases fail with an empty rule set.

- [ ] **Step 3: Implement `labbrain/lint/rules/link_rules.py`**

```python
"""broken-link and orphan."""

from __future__ import annotations

from collections.abc import Iterator

from labbrain.findings import ERROR, WARNING, Finding
from labbrain.lint import LintContext, rule

ORPHAN_EXEMPT = frozenset({"idea", "handoff"})


def _vault_filenames(ctx: LintContext) -> set[str]:
    if "filenames" not in ctx.cache:
        root = ctx.vault.root
        ctx.cache["filenames"] = {
            p.name
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts
        }
    return ctx.cache["filenames"]


def _path_exists(ctx: LintContext, target: str) -> bool:
    if "/" in target:
        return (ctx.vault.root / target).exists()
    return target in _vault_filenames(ctx)  # Obsidian resolves bare filenames anywhere


@rule("broken-link", ERROR, "Every wikilink and ID-bearing frontmatter value resolves")
def broken_link(ctx: LintContext) -> Iterator[Finding]:
    for note in ctx.vault.all_notes():
        for ref in note.refs:
            if ref.is_path:
                if not _path_exists(ctx, ref.target):
                    message = f"{ref.field}: missing file {ref.target}"
                    yield Finding(note.rel, ref.line, "broken-link", ERROR, message)
            elif ref.target not in ctx.vault.notes:
                message = f"{ref.field}: unresolved link [[{ref.target}]]"
                yield Finding(note.rel, ref.line, "broken-link", ERROR, message)


@rule("orphan", WARNING, "Note with no inbound links (ideas and handoffs exempt)")
def orphan(ctx: LintContext) -> Iterator[Finding]:
    for stem, note in ctx.vault.notes.items():
        if note.type is None or note.type in ORPHAN_EXEMPT:
            continue
        if not ctx.vault.inbound.get(stem):
            yield Finding(note.rel, 1, "orphan", WARNING, "no inbound links")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_link_rules.py tests/test_gate.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; the valid fixture is still clean with four rules active.

- [ ] **Step 5: Commit**

```bash
git add labbrain/lint/rules/link_rules.py tests
git commit -m "feat(lint): broken-link and orphan rules" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Protocol and claim rules

**Files:**
- Create: `labbrain/lint/rules/protocol_rules.py`
- Modify: `tests/fixtures/mutations.py` (append)
- Test: `tests/test_protocol_rules.py`

**Interfaces:**
- Consumes: `LintContext`, `rule`, `Vault.get`, `Vault.of_type`, `Note.get_str`, `Note.get_list`.
- Produces: `comparable(a: str, b: str, vault: Vault) -> bool`; rules `protocol-missing` (error), `cross-protocol` (error), `claim-stale` (warning), `duplicate-config` (warning). Task 10 adds `sync-pending` to this module.

- [ ] **Step 1: Write the failing tests**

`tests/test_protocol_rules.py`:

```python
from __future__ import annotations

from pathlib import Path

from fixtures.mutations import BASELINE, CLAIM, EVAL_V1, EVAL_V2, SMOOTHING, replace
from helpers import TODAY

from labbrain import lint
from labbrain.lint.rules.protocol_rules import comparable
from labbrain.vault import Vault


def fired(root: Path, *rules: str) -> list[tuple[str, str]]:
    return [(f.rule, f.path) for f in lint.run(Vault.load(root), today=TODAY, only=rules)]


def test_comparable_is_reflexive_and_symmetric_not_transitive(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "comparable_with: []", "comparable_with: [EVAL-v1]")
    vault = Vault.load(vault_dir)
    assert comparable("EVAL-v2", "EVAL-v2", vault)
    assert comparable("EVAL-v2", "EVAL-v1", vault)
    assert comparable("EVAL-v1", "EVAL-v2", vault)  # symmetric: v1 is frozen, cannot list v2
    assert not comparable("EVAL-v1", "EVAL-v3", vault)


def test_cross_protocol_respects_declared_comparability(vault_dir: Path) -> None:
    replace(vault_dir, CLAIM, "protocol: EVAL-v2", "protocol: EVAL-v1")
    assert fired(vault_dir, "cross-protocol") == [("cross-protocol", CLAIM)]
    replace(vault_dir, EVAL_V1, "comparable_with: []", "comparable_with: [EVAL-v2]")
    assert fired(vault_dir, "cross-protocol") == []


def test_cross_protocol_skips_evidence_without_protocol(vault_dir: Path) -> None:
    replace(vault_dir, CLAIM, "protocol: EVAL-v2", "protocol: EVAL-v1")
    replace(vault_dir, BASELINE, "protocol: EVAL-v2\n", "")
    assert fired(vault_dir, "cross-protocol") == []


def test_duplicate_config_ignores_supersession_pairs(vault_dir: Path) -> None:
    hash_line = 'config_hash: "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"'
    baseline_hash = (
        'config_hash: "sha256:3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b"'
    )
    replace(vault_dir, SMOOTHING, hash_line, baseline_hash)
    assert sorted(fired(vault_dir, "duplicate-config")) == [
        ("duplicate-config", BASELINE),
        ("duplicate-config", SMOOTHING),
    ]
    replace(
        vault_dir,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )
    assert fired(vault_dir, "duplicate-config") == []
```

Append to `tests/fixtures/mutations.py`:

```python
# --- protocol and claim rules ------------------------------------------------------


@mutation("protocol-missing")
def protocol_missing(vault: Path) -> None:
    """Done experiment loses `protocol`; EVAL-v2 keeps inbound links from the baseline,
    the claim and the decision, and the claim's evidence is the baseline."""
    replace(vault, SMOOTHING, "protocol: EVAL-v2\n", "")


@mutation("cross-protocol")
def cross_protocol(vault: Path) -> None:
    """Claim moves to EVAL-v1, which nothing declares comparable with EVAL-v2."""
    replace(vault, CLAIM, "protocol: EVAL-v2", "protocol: EVAL-v1")


@mutation("claim-stale")
def claim_stale_failed_evidence(vault: Path) -> None:
    """The claim's evidence experiment is now `failed`. EVAL-v2 is still referenced by the
    other done experiment, so sync has nothing to do."""
    replace(vault, BASELINE, "status: done", "status: failed")


@mutation("duplicate-config")
def duplicate_config(vault: Path) -> None:
    """Both done experiments share a config hash and protocol and neither supersedes."""
    replace(
        vault,
        SMOOTHING,
        'config_hash: "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"',
        'config_hash: "sha256:3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b"',
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_protocol_rules.py tests/test_gate.py -v`
Expected: `ModuleNotFoundError: No module named 'labbrain.lint.rules.protocol_rules'` in `test_protocol_rules.py`; the four new gate cases fail.

- [ ] **Step 3: Implement `labbrain/lint/rules/protocol_rules.py`**

```python
"""protocol-missing, cross-protocol, claim-stale and duplicate-config.

These rules read raw frontmatter (Note.get_*), never the pydantic model, so a
note with one bad field is still checked for everything else.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from labbrain.findings import ERROR, WARNING, Finding
from labbrain.lint import LintContext, rule
from labbrain.notes import Note
from labbrain.vault import Vault

STALE_EVIDENCE = frozenset({"superseded", "failed"})


def comparable(a: str, b: str, vault: Vault) -> bool:
    """Reflexive and symmetric, not transitive. Older protocols are frozen and cannot
    list newer ones, so either side may declare comparability."""
    if a == b:
        return True
    pa, pb = vault.get(a), vault.get(b)
    return (pa is not None and b in pa.get_list("comparable_with")) or (
        pb is not None and a in pb.get_list("comparable_with")
    )


@rule("protocol-missing", ERROR, "Experiment with status done and no protocol")
def protocol_missing(ctx: LintContext) -> Iterator[Finding]:
    for exp in ctx.vault.of_type("experiment"):
        if exp.get_str("status") == "done" and not exp.get_str("protocol"):
            yield Finding(exp.rel, 1, "protocol-missing", ERROR, "done experiment has no protocol")


@rule("cross-protocol", ERROR, "Claim evidence uses a protocol not comparable with the claim's")
def cross_protocol(ctx: LintContext) -> Iterator[Finding]:
    for claim in ctx.vault.of_type("claim"):
        claim_protocol = claim.get_str("protocol")
        if not claim_protocol:
            continue
        for evidence_id in claim.get_list("evidence"):
            exp = ctx.vault.get(evidence_id)
            if exp is None or exp.type != "experiment":
                continue
            exp_protocol = exp.get_str("protocol")
            if exp_protocol and not comparable(claim_protocol, exp_protocol, ctx.vault):
                message = (
                    f"evidence {evidence_id} uses {exp_protocol}, "
                    f"not comparable with the claim's {claim_protocol}"
                )
                yield Finding(claim.rel, 1, "cross-protocol", ERROR, message)


@rule("claim-stale", WARNING, "Claim evidence is superseded or failed")
def claim_stale(ctx: LintContext) -> Iterator[Finding]:
    for claim in ctx.vault.of_type("claim"):
        for evidence_id in claim.get_list("evidence"):
            exp = ctx.vault.get(evidence_id)
            status = exp.get_str("status") if exp is not None else None
            if exp is not None and exp.type == "experiment" and status in STALE_EVIDENCE:
                yield Finding(
                    claim.rel, 1, "claim-stale", WARNING, f"evidence {evidence_id} is {status}"
                )


def _supersession_pair(a: Note, b: Note) -> bool:
    return a.get_str("supersedes") == b.stem or b.get_str("supersedes") == a.stem


@rule("duplicate-config", WARNING, "Two live experiments share config_hash and protocol")
def duplicate_config(ctx: LintContext) -> Iterator[Finding]:
    groups: dict[tuple[str, str], list[Note]] = defaultdict(list)
    for exp in ctx.vault.of_type("experiment"):
        config_hash, protocol = exp.get_str("config_hash"), exp.get_str("protocol")
        if config_hash and protocol and exp.get_str("status") != "superseded":
            groups[(config_hash, protocol)].append(exp)
    for group in groups.values():
        for exp in group:
            others = sorted(
                o.stem for o in group if o is not exp and not _supersession_pair(exp, o)
            )
            if others:
                message = f"same config_hash and protocol as {', '.join(others)}"
                yield Finding(exp.rel, 1, "duplicate-config", WARNING, message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_protocol_rules.py tests/test_gate.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add labbrain/lint/rules/protocol_rules.py tests
git commit -m "feat(lint): protocol-missing, cross-protocol, claim-stale, duplicate-config" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `labbrain sync` and the `sync-pending` rule

**Files:**
- Create: `labbrain/sync.py`
- Modify: `labbrain/lint/rules/protocol_rules.py` (append rule), `tests/fixtures/mutations.py` (append)
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `Vault`, `update_frontmatter`.
- Produces (`labbrain.sync`): frozen dataclasses `Change(note_id: str, rel: str, updates: dict[str, Any], reason: str)` and `Conflict(note_id: str, rel: str, message: str)`; `plan(vault) -> tuple[list[Change], list[Conflict]]`; `apply(vault, changes, today: date) -> list[str]` (vault-relative paths written; also sets `updated`).
- Produces: rule `sync-pending` (warning per pending change, error per conflict).

- [ ] **Step 1: Write the failing tests**

`tests/test_sync.py`:

```python
from __future__ import annotations

from datetime import date
from pathlib import Path

from fixtures.mutations import BASELINE, EVAL_V2, SMOOTHING, replace
from helpers import TODAY, body_for, make_vault, note_text, write

from labbrain import lint
from labbrain.sync import Change, apply, plan
from labbrain.vault import Vault

SUPERSEDES = (
    "links: [EXP-20260901-baseline]",
    "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
)


def test_valid_fixture_has_nothing_to_sync(vault_dir: Path) -> None:
    assert plan(Vault.load(vault_dir)) == ([], [])


def test_supersession_is_planned_applied_and_idempotent(vault_dir: Path) -> None:
    replace(vault_dir, SMOOTHING, *SUPERSEDES)
    vault = Vault.load(vault_dir)
    changes, conflicts = plan(vault)
    assert conflicts == []
    assert changes == [
        Change(
            "EXP-20260901-baseline",
            BASELINE,
            {"status": "superseded", "superseded_by": "EXP-20260910-label-smoothing"},
            "superseded by EXP-20260910-label-smoothing",
        )
    ]
    assert apply(vault, changes, TODAY) == [BASELINE]
    text = (vault_dir / BASELINE).read_text()
    assert "status: superseded\n" in text
    assert "superseded_by: EXP-20260910-label-smoothing\n" in text
    assert "updated: 2026-10-15\n" in text
    assert plan(Vault.load(vault_dir)) == ([], [])


def test_draft_protocol_referenced_by_done_experiment_is_frozen(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "status: frozen", "status: draft")
    changes, _ = plan(Vault.load(vault_dir))
    assert [(c.note_id, c.updates) for c in changes] == [("EVAL-v2", {"status": "frozen"})]


def test_conflicting_supersession_is_reported_not_written(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    old = note_text("ADR-20261001-old", "decision", status="accepted")
    write(root, "decisions/ADR-20261001-old.md", old)
    for name in ("a", "b"):
        write(
            root,
            f"decisions/ADR-20261002-{name}.md",
            note_text(f"ADR-20261002-{name}", "decision", supersedes="ADR-20261001-old"),
        )
    changes, conflicts = plan(Vault.load(root))
    assert changes == []
    assert [c.note_id for c in conflicts] == ["ADR-20261001-old"]
    assert "more than one" in conflicts[0].message


def test_already_superseded_by_someone_else(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(
        root,
        "decisions/ADR-20261001-old.md",
        note_text(
            "ADR-20261001-old", "decision", status="superseded", superseded_by="ADR-20261002-a"
        ),
    )
    write(
        root,
        "decisions/ADR-20261002-b.md",
        note_text("ADR-20261002-b", "decision", supersedes="ADR-20261001-old", body=body_for("decision")),
    )
    changes, conflicts = plan(Vault.load(root))
    assert changes == []
    assert "already superseded by ADR-20261002-a" in conflicts[0].message


def test_sync_pending_rule(vault_dir: Path) -> None:
    replace(vault_dir, SMOOTHING, *SUPERSEDES)
    findings = lint.run(Vault.load(vault_dir), today=date(2026, 10, 15), only=["sync-pending"])
    assert [(f.rule, f.severity, f.path) for f in findings] == [
        ("sync-pending", "warning", BASELINE)
    ]
```

Append to `tests/fixtures/mutations.py`:

```python
# --- sync-pending ------------------------------------------------------------------


@mutation("sync-pending")
def sync_pending_supersession(vault: Path) -> None:
    """label-smoothing now supersedes the baseline but sync has not run: the baseline is
    still `done`, so claim-stale stays quiet, and the two config hashes differ."""
    replace(
        vault,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )


@mutation("sync-pending")
def sync_pending_protocol(vault: Path) -> None:
    """EVAL-v2 is `draft` although done experiments reference it (committed, so no
    frozen-edit)."""
    replace(vault, EVAL_V2, "status: frozen", "status: draft")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync.py tests/test_gate.py -v`
Expected: `ModuleNotFoundError: No module named 'labbrain.sync'`; the two new gate cases fail.

- [ ] **Step 3: Implement `labbrain/sync.py`**

```python
"""Derived state the tool maintains: supersession links and protocol freezing.

Idempotent, and it only performs transitions that frozen-edit allows, so its
output never trips frozen-edit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from labbrain.notes import update_frontmatter
from labbrain.vault import Vault


@dataclass(frozen=True)
class Change:
    note_id: str
    rel: str
    updates: dict[str, Any]
    reason: str


@dataclass(frozen=True)
class Conflict:
    note_id: str
    rel: str
    message: str


def plan(vault: Vault) -> tuple[list[Change], list[Conflict]]:
    changes: list[Change] = []
    conflicts: list[Conflict] = []

    successors: dict[str, list[str]] = defaultdict(list)
    for note in vault.notes.values():
        target = note.get_str("supersedes")
        if target:
            successors[target].append(note.stem)
    for old_id in sorted(successors):
        old = vault.get(old_id)
        if old is None:
            continue  # broken-link reports it
        news = sorted(successors[old_id])
        if len(news) > 1:
            message = f"{old_id} is superseded by more than one note: {', '.join(news)}"
            conflicts.append(Conflict(old_id, old.rel, message))
            continue
        new = news[0]
        current = old.get_str("superseded_by")
        if current and current != new:
            message = f"{old_id} is already superseded by {current}; {new} also claims to supersede it"
            conflicts.append(Conflict(old_id, old.rel, message))
            continue
        updates: dict[str, Any] = {}
        if old.get_str("status") != "superseded":
            updates["status"] = "superseded"
        if current != new:
            updates["superseded_by"] = new
        if updates:
            changes.append(Change(old_id, old.rel, updates, f"superseded by {new}"))

    done_protocols = {
        exp.get_str("protocol")
        for exp in vault.of_type("experiment")
        if exp.get_str("status") == "done"
    }
    for protocol_id in sorted(p for p in done_protocols if p):
        protocol = vault.get(protocol_id)
        if protocol is not None and protocol.type == "protocol" and protocol.get_str("status") == "draft":
            changes.append(
                Change(protocol_id, protocol.rel, {"status": "frozen"}, "referenced by a done experiment")
            )
    return changes, conflicts


def apply(vault: Vault, changes: list[Change], today: date) -> list[str]:
    written = []
    for change in changes:
        if update_frontmatter(vault.root / change.rel, {**change.updates, "updated": today}):
            written.append(change.rel)
    return written
```

- [ ] **Step 4: Append the rule to `labbrain/lint/rules/protocol_rules.py`**

Add `from labbrain.sync import plan as sync_plan` to the imports, then append:

```python
@rule("sync-pending", WARNING, "`labbrain sync` would change something; conflicts are errors")
def sync_pending(ctx: LintContext) -> Iterator[Finding]:
    changes, conflicts = sync_plan(ctx.vault)
    for change in changes:
        fields = ", ".join(f"{key} → {value}" for key, value in change.updates.items())
        message = f"run `labbrain sync`: {fields} ({change.reason})"
        yield Finding(change.rel, 1, "sync-pending", WARNING, message)
    for conflict in conflicts:
        yield Finding(conflict.rel, 1, "sync-pending", ERROR, conflict.message)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sync.py tests/test_gate.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add labbrain/sync.py labbrain/lint/rules/protocol_rules.py tests
git commit -m "feat(sync): supersession propagation, protocol freezing, sync-pending rule" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: `index.md`, daily log, and the `index-stale` rule

**Files:**
- Create: `labbrain/index.py`, `labbrain/log.py`, `labbrain/lint/rules/hygiene_rules.py`, `tests/fixtures/valid/index.md` (generated)
- Modify: `tests/fixtures/mutations.py` (append)
- Test: `tests/test_index.py`, `tests/test_log.py`

**Interfaces:**
- Consumes: `Vault`, `Note`, `iter_body_lines`, `HEADING_RE`, `atomic_write`, `FUTURE_AGENTS_HEADING`, `INDEX_FILE`, `LOG_DIR`.
- Produces (`labbrain.index`): `TYPE_ORDER`, `summary(note) -> str`, `render(vault) -> str`, `write(vault) -> bool` (True if changed), `is_stale(vault) -> bool | None` (None when `index.md` is absent).
- Produces (`labbrain.log`): `append(root, text, *, when: datetime, author: str | None = None) -> Path`.
- Produces: rule `index-stale` (warning) in `hygiene_rules.py`; Task 12 adds four more rules to that module.

- [ ] **Step 1: Write the failing tests**

`tests/test_index.py`:

```python
from __future__ import annotations

from pathlib import Path

from fixtures.mutations import CONCEPT, replace
from helpers import FIXTURE, TODAY, body_for, make_vault, note_text, write

from labbrain import lint
from labbrain.index import is_stale, render, summary
from labbrain.notes import parse_note_text
from labbrain.vault import Vault

EXPECTED_INDEX = """# Index

<!-- Generated by `labbrain index`. Do not edit by hand. -->

## Experiments

- [[EXP-20260910-label-smoothing]] — Label smoothing vs. calibration — Label smoothing improves calibration without lowering AUROC.
- [[EXP-20260901-baseline]] — Baseline classifier — A plain ResNet reaches a usable AUROC on the main split.

## Claims

- [[CLM-20261001-median-auroc]] — Median AUROC of the baseline — Median AUROC 0.81 on the test split, from [[EXP-20260901-baseline]] (run-001).

## Concepts

- [[label-smoothing-calibration]] — Label smoothing and calibration — Label smoothing regularises over-confident logits, which tends to improve calibration.

## Decisions

- [[ADR-20260905-adopt-eval-v2]] — Adopt EVAL-v2 for all new experiments — Accuracy under EVAL-v1 hid calibration problems; see [[label-smoothing-calibration]] and [[LIT-szegedy2016-rethinking]].

## Protocols

- [[EVAL-v2]] — AUROC and ECE on the main split — Median one-vs-rest AUROC and expected calibration error (15 bins) on the test split of [[DS-20260801-main-split]].
- [[EVAL-v1]] — Held-out accuracy, single split — Top-1 accuracy on the public test split; no class reweighting.

## Datasets

- [[DS-20260801-main-split]] — Public benchmark, main split — A public image classification benchmark, downloaded unchanged.

## Literature

- [[LIT-szegedy2016-rethinking]] — Rethinking the Inception Architecture for Computer Vision — Introduces label smoothing as a regulariser for classification.

## Ideas

- [[IDEA-20261010-smoothing-schedule]] — Anneal label smoothing over training — Anneal the smoothing value to zero over training and see whether late-epoch calibration holds.
- [[IDEA-20260912-smoothing-helps]] — Label smoothing might fix over-confidence — Over-confident logits on the baseline might be tamed by label smoothing.

## Handoffs

- [[HO-20261014-1420-claude]] — Registered the headline AUROC claim — Checked [[CLM-20261001-median-auroc]] against [[EXP-20260901-baseline]] and [[EXP-20260910-label-smoothing]].
"""


def test_render_fixture() -> None:
    assert render(Vault.load(FIXTURE)) == EXPECTED_INDEX


def test_committed_fixture_index_is_current() -> None:
    assert (FIXTURE / "index.md").read_text() == EXPECTED_INDEX


def summary_of(body: str) -> str:
    text = "---\nid: x\ntype: concept\n---\n" + body
    return summary(parse_note_text(text, Path("concepts/x.md"), "concepts/x.md"))


def test_summary_rules() -> None:
    assert summary_of("## For future agents\n\nskip me\n\n## Summary\n\nFirst. Second.\n") == "First."
    assert summary_of("| a | b |\n|---|---|\n\nAfter the table.\n") == "After the table."
    assert summary_of("Value 0.81 holds. Next.\n") == "Value 0.81 holds."
    assert summary_of("") == ""
    long = summary_of("word " * 60 + "end.\n")
    assert len(long) == 160 and long.endswith("…")


def test_order_newest_first_then_id(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    for note_id, created in [("ADR-20261001-b", "2026-10-01"), ("ADR-20261001-a", "2026-10-01"), ("ADR-20261003-c", "2026-10-03")]:
        write(root, f"decisions/{note_id}.md", note_text(note_id, "decision", created=created, body=body_for("decision")))
    lines = [line for line in render(Vault.load(root)).splitlines() if line.startswith("- ")]
    assert [line.split("]]")[0][4:] for line in lines] == [
        "ADR-20261003-c",
        "ADR-20261001-a",
        "ADR-20261001-b",
    ]


def test_is_stale_and_rule(vault_dir: Path) -> None:
    vault = Vault.load(vault_dir)
    assert is_stale(vault) is False
    assert lint.run(vault, today=TODAY, only=["index-stale"]) == []
    replace(vault_dir, CONCEPT, 'title: "Label smoothing and calibration"', 'title: "Renamed"')
    vault = Vault.load(vault_dir)
    assert is_stale(vault) is True
    assert [f.rule for f in lint.run(vault, today=TODAY, only=["index-stale"])] == ["index-stale"]
    (vault_dir / "index.md").unlink()
    assert is_stale(Vault.load(vault_dir)) is None
```

`tests/test_log.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from labbrain.log import append

WHEN = datetime(2026, 10, 15, 9, 5)


def test_append_lines(tmp_path: Path) -> None:
    path = append(tmp_path, "exp-log: logged EXP-20261015-x", when=WHEN, author="claude")
    append(tmp_path, "idea:  multi\nline ", when=WHEN)
    assert path == tmp_path / "log" / "2026-10-15.md"
    assert path.read_text() == (
        "- 09:05 [claude] exp-log: logged EXP-20261015-x\n- 09:05 idea: multi line\n"
    )


def test_append_repairs_missing_trailing_newline(tmp_path: Path) -> None:
    (tmp_path / "log").mkdir()
    (tmp_path / "log" / "2026-10-15.md").write_text("- 08:00 earlier")
    path = append(tmp_path, "later", when=WHEN)
    assert path.read_text() == "- 08:00 earlier\n- 09:05 later\n"


def test_append_rejects_empty_text(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        append(tmp_path, "   ", when=WHEN)
```

Append to `tests/fixtures/mutations.py`:

```python
# --- index-stale ---------------------------------------------------------------------


@mutation("index-stale", keep_index=True)
def index_stale_title(vault: Path) -> None:
    """The concept's title changes after the index was generated; titles are free text."""
    replace(
        vault,
        CONCEPT,
        'title: "Label smoothing and calibration"',
        'title: "Label smoothing, calibration and confidence"',
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_index.py tests/test_log.py -v`
Expected: `ModuleNotFoundError: No module named 'labbrain.index'` and `'labbrain.log'`.

- [ ] **Step 3: Implement `labbrain/index.py`**

```python
"""index.md: the catalog agents read first. Generated, gitignored, never hand-edited."""

from __future__ import annotations

import re

from labbrain.layout import INDEX_FILE
from labbrain.notes import HEADING_RE, Note, atomic_write, iter_body_lines
from labbrain.schema import FUTURE_AGENTS_HEADING
from labbrain.vault import Vault

TYPE_ORDER: tuple[str, ...] = (
    "experiment",
    "claim",
    "concept",
    "decision",
    "protocol",
    "dataset",
    "literature",
    "idea",
    "handoff",
)
_HEADINGS = {
    "experiment": "Experiments",
    "claim": "Claims",
    "concept": "Concepts",
    "decision": "Decisions",
    "protocol": "Protocols",
    "dataset": "Datasets",
    "literature": "Literature",
    "idea": "Ideas",
    "handoff": "Handoffs",
}
SUMMARY_MAX = 160
HEADER = "# Index\n\n<!-- Generated by `labbrain index`. Do not edit by hand. -->\n"
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def summary(note: Note) -> str:
    """First sentence of the first paragraph after the For-future-agents block."""
    lines = [line for _, line in iter_body_lines(note)]
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].strip() == f"## {FUTURE_AGENTS_HEADING}":
        i += 1
        while i < len(lines) and not HEADING_RE.match(lines[i]):
            i += 1
    paragraph: list[str] = []
    for line in lines[i:]:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "<!--")):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    text = " ".join(paragraph)
    sentence = _SENTENCE_END.split(text, maxsplit=1)[0] if text else ""
    if len(sentence) > SUMMARY_MAX:
        sentence = sentence[: SUMMARY_MAX - 1].rstrip() + "…"
    return sentence


def _created(note: Note) -> str:
    created = note.get_date("created")
    return created.isoformat() if created else ""


def render(vault: Vault) -> str:
    parts = [HEADER]
    for note_type in TYPE_ORDER:
        notes = sorted(vault.of_type(note_type), key=lambda n: n.stem)
        notes.sort(key=_created, reverse=True)  # stable: ties stay in ID order
        if not notes:
            continue
        parts.append(f"\n## {_HEADINGS[note_type]}\n\n")
        for note in notes:
            line = f"- [[{note.stem}]] — {note.get_str('title') or ''}"
            text = summary(note)
            if text:
                line += f" — {text}"
            parts.append(line + "\n")
    return "".join(parts)


def write(vault: Vault) -> bool:
    path = vault.root / INDEX_FILE
    text = render(vault)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    atomic_write(path, text)
    return True


def is_stale(vault: Vault) -> bool | None:
    path = vault.root / INDEX_FILE
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8") != render(vault)
```

- [ ] **Step 4: Implement `labbrain/log.py`**

```python
"""Daily activity log: one line per writing-skill action in log/YYYY-MM-DD.md.

No frontmatter, so vault templates can mark log/ with git's union merge driver
and concurrent appends from two lab members never conflict.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from labbrain.layout import LOG_DIR


def append(root: Path, text: str, *, when: datetime, author: str | None = None) -> Path:
    message = " ".join(text.split())
    if not message:
        raise ValueError("log text is empty")
    path = root / LOG_DIR / f"{when:%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"- {when:%H:%M}" + (f" [{author}]" if author else "") + f" {message}\n"
    prefix = ""
    if path.is_file() and path.stat().st_size and not path.read_bytes().endswith(b"\n"):
        prefix = "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + line)
    return path
```

- [ ] **Step 5: Create `labbrain/lint/rules/hygiene_rules.py` with `index-stale`**

```python
"""Hygiene rules: index-stale, concept-unsourced, inbox-age, dirty-code, undated-fact."""

from __future__ import annotations

from collections.abc import Iterator

from labbrain.findings import WARNING, Finding
from labbrain.index import is_stale
from labbrain.layout import INDEX_FILE
from labbrain.lint import LintContext, rule


@rule("index-stale", WARNING, "index.md differs from what `labbrain index` would generate")
def index_stale(ctx: LintContext) -> Iterator[Finding]:
    if is_stale(ctx.vault):
        message = "index.md is out of date; run `labbrain index`"
        yield Finding(INDEX_FILE, 0, "index-stale", WARNING, message)
```

- [ ] **Step 6: Generate the fixture index**

Run:

```bash
uv run python -c "from pathlib import Path; from labbrain.index import write; from labbrain.vault import Vault; write(Vault.load(Path('tests/fixtures/valid')))"
```

Expected: `tests/fixtures/valid/index.md` now exists and equals `EXPECTED_INDEX`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_index.py tests/test_log.py tests/test_gate.py tests/test_fixture.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; the valid fixture stays clean now that `index-stale` is active.

- [ ] **Step 8: Commit**

```bash
git add labbrain/index.py labbrain/log.py labbrain/lint/rules/hygiene_rules.py tests
git commit -m "feat(index): generated index.md, daily log, index-stale rule" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Remaining hygiene rules

**Files:**
- Modify: `labbrain/lint/rules/hygiene_rules.py` (append four rules), `tests/fixtures/mutations.py` (append)
- Test: `tests/test_hygiene_rules.py`

**Interfaces:**
- Consumes: `H2_RE`, `iter_body_lines`, `FUTURE_AGENTS_HEADING`, `Config.is_agent`, `Config.id_prefixes`, `Config.inbox_max_days`, `LintContext.today`.
- Produces: rules `concept-unsourced`, `inbox-age`, `dirty-code`, `undated-fact` (all warnings); `METRIC_RE: re.Pattern`.

- [ ] **Step 1: Write the failing tests**

`tests/test_hygiene_rules.py`:

````python
from __future__ import annotations

from datetime import date
from pathlib import Path

from helpers import body_for, make_vault, note_text, write

from labbrain import lint
from labbrain.lint.rules.hygiene_rules import METRIC_RE
from labbrain.vault import Vault

TODAY = date(2026, 10, 15)


def fired(root: Path, rule: str) -> list[int]:
    return [f.line for f in lint.run(Vault.load(root), today=TODAY, only=[rule])]


def concept(root: Path, body: str, author: str = "claude") -> Path:
    block = "## For future agents\n\nA concept.\n\n" if author == "claude" else ""
    text = note_text("topic", "concept", author=author, sources=["x"], body=block + body)
    return write(root, "concepts/topic.md", text)


def test_metric_regex() -> None:
    assert METRIC_RE.search("ECE 0.04")
    assert METRIC_RE.search("accuracy 87%")
    assert METRIC_RE.search("gain of 12.5 %")
    assert not METRIC_RE.search("on 2026-10-15")
    assert not METRIC_RE.search("smoothing 0.1 only")
    assert not METRIC_RE.search("version v1.25")
    assert not METRIC_RE.search("EXP-20261015-x")


def test_undated_fact_flags_unstamped_lines_only(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    body = (
        "## Summary\n\n"
        "ECE fell to 0.04.\n"  # flagged
        "ECE fell to 0.04 in [[EXP-20261001-a]].\n"
        "ECE fell to 0.04 as of 2026-10-01.\n"
        "ECE fell to 0.04 (run_id r1).\n"
        "Accuracy 87% overall.\n"  # flagged
        "```\n0.99 inside a fence\n```\n"
        "## History\n\n- 2026-10-01: value 0.81\n"
    )
    path = concept(root, body)
    lines = path.read_text().splitlines()
    flagged = fired(root, "undated-fact")
    assert [lines[n - 1] for n in flagged] == ["ECE fell to 0.04.", "Accuracy 87% overall."]


def test_undated_fact_ignores_humans_and_experiments(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    concept(root, "## Summary\n\nECE fell to 0.04.\n", author="alice")
    write(
        root,
        "experiments/EXP-20261001-a.md",
        note_text("EXP-20261001-a", "experiment", author="alice", body=body_for("experiment", "AUROC 0.81")),
    )
    assert fired(root, "undated-fact") == []


def test_concept_unsourced(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "concepts/a.md", note_text("a", "concept", sources=[]))
    write(root, "concepts/b.md", note_text("b", "concept", sources=["a"]))
    findings = lint.run(Vault.load(root), today=TODAY, only=["concept-unsourced"])
    assert [f.path for f in findings] == ["concepts/a.md"]


def test_inbox_age_boundary(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "ideas/inbox/IDEA-20260915-a.md", note_text("IDEA-20260915-a", "idea", created=date(2026, 9, 15), body="x\n"))
    write(root, "ideas/inbox/IDEA-20260914-b.md", note_text("IDEA-20260914-b", "idea", created=date(2026, 9, 14), body="x\n"))
    findings = lint.run(Vault.load(root), today=TODAY, only=["inbox-age"])
    assert [f.path for f in findings] == ["ideas/inbox/IDEA-20260914-b.md"]  # 31 days > 30


def test_dirty_code(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    write(root, "experiments/EXP-20261001-a.md", note_text("EXP-20261001-a", "experiment", code={"sha": "1a2b3c4", "dirty": True}))
    write(root, "experiments/EXP-20261001-b.md", note_text("EXP-20261001-b", "experiment", code={"sha": "1a2b3c4", "dirty": False}))
    findings = lint.run(Vault.load(root), today=TODAY, only=["dirty-code"])
    assert [f.path for f in findings] == ["experiments/EXP-20261001-a.md"]
````

Append to `tests/fixtures/mutations.py`:

```python
# --- hygiene -------------------------------------------------------------------------


@mutation("concept-unsourced")
def concept_unsourced(vault: Path) -> None:
    """Concept sources emptied. label-smoothing keeps inbound links from the concept body
    and the handoff; the paper keeps the concept body and the decision."""
    replace(
        vault,
        CONCEPT,
        "sources: [EXP-20260910-label-smoothing, LIT-szegedy2016-rethinking]",
        "sources: []",
    )


@mutation("inbox-age")
def inbox_age(vault: Path) -> None:
    """The open idea was created more than 30 days before the pinned date."""
    replace(vault, IDEA_OPEN, "created: 2026-10-10", "created: 2026-08-01")


@mutation("dirty-code")
def dirty_code(vault: Path) -> None:
    """The baseline was logged from a dirty tree."""
    replace(vault, BASELINE, "dirty: false", "dirty: true")


@mutation("undated-fact")
def undated_fact(vault: Path) -> None:
    """An agent-written concept quotes a number with no stamp; no PHI pattern matches."""
    replace(
        vault,
        CONCEPT,
        "which tends to improve calibration.\n",
        "which tends to improve calibration.\n\nIn our runs calibration error dropped to 0.04.\n",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hygiene_rules.py tests/test_gate.py -v`
Expected: `ImportError: cannot import name 'METRIC_RE'`; the four new gate cases fail.

- [ ] **Step 3: Append the rules to `labbrain/lint/rules/hygiene_rules.py`**

Add these imports at the top: `import re`, `from labbrain.notes import H2_RE, iter_body_lines`, `from labbrain.schema import FUTURE_AGENTS_HEADING`. Then append:

```python
# Percentages, or decimals with at least two fractional digits.
METRIC_RE = re.compile(r"(?<![\w.])(?:\d+(?:\.\d+)?\s?%|\d*\.\d{2,})(?![\w.])")
_AS_OF_RE = re.compile(r"\bas of \d{4}-\d{2}-\d{2}\b", re.IGNORECASE)
_RUN_RE = re.compile(r"\brun_id\b|\brun:")
UNDATED_TYPES = frozenset({"concept", "claim"})
UNDATED_SKIP_SECTIONS = frozenset({"History", FUTURE_AGENTS_HEADING})


@rule("concept-unsourced", WARNING, "Concept with sources: []")
def concept_unsourced(ctx: LintContext) -> Iterator[Finding]:
    for note in ctx.vault.of_type("concept"):
        if note.data is not None and "sources" in note.data and not note.get_list("sources"):
            yield Finding(note.rel, 1, "concept-unsourced", WARNING, "concept cites no sources")


@rule("inbox-age", WARNING, "Open idea older than inbox_max_days")
def inbox_age(ctx: LintContext) -> Iterator[Finding]:
    limit = ctx.vault.config.inbox_max_days
    for note in ctx.vault.of_type("idea"):
        created = note.get_date("created")
        if note.get_str("status") == "open" and created and (ctx.today - created).days > limit:
            age = (ctx.today - created).days
            message = f"open for {age} days (limit {limit}); consolidate or drop it"
            yield Finding(note.rel, 1, "inbox-age", WARNING, message)


@rule("dirty-code", WARNING, "Experiment logged from a dirty code tree")
def dirty_code(ctx: LintContext) -> Iterator[Finding]:
    for note in ctx.vault.of_type("experiment"):
        code = note.get("code")
        if isinstance(code, dict) and code.get("dirty") is True:
            message = "logged from a dirty code tree; the SHA does not identify the code that ran"
            yield Finding(note.rel, 1, "dirty-code", WARNING, message)


def _stamp_re(prefixes: dict[str, str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(prefixes[t]) for t in ("experiment", "literature", "claim"))
    return re.compile(rf"\[\[(?:{alternatives})-")


@rule("undated-fact", WARNING, "Agent-written metric-like number without a run, link or date")
def undated_fact(ctx: LintContext) -> Iterator[Finding]:
    config = ctx.vault.config
    stamp = _stamp_re(config.id_prefixes)
    for note in ctx.vault.notes.values():
        if note.type not in UNDATED_TYPES or not config.is_agent(note.get_str("author")):
            continue
        section: str | None = None
        for lineno, line in iter_body_lines(note):
            heading = H2_RE.match(line)
            if heading:
                section = heading.group(1)
                continue
            if section in UNDATED_SKIP_SECTIONS or line.lstrip().startswith("#"):
                continue
            if METRIC_RE.search(line) and not (
                stamp.search(line) or _RUN_RE.search(line) or _AS_OF_RE.search(line)
            ):
                message = "metric-like number without an EXP/LIT/CLM link, run id or 'as of' date"
                yield Finding(note.rel, lineno, "undated-fact", WARNING, message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hygiene_rules.py tests/test_gate.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add labbrain/lint/rules/hygiene_rules.py tests
git commit -m "feat(lint): concept-unsourced, inbox-age, dirty-code, undated-fact" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Git access and the `frozen-edit` rule

**Files:**
- Create: `labbrain/gitutil.py`, `labbrain/lint/rules/frozen_rules.py`
- Modify: `tests/fixtures/mutations.py` (append)
- Test: `tests/test_gitutil.py`, `tests/test_frozen.py`

**Interfaces:**
- Consumes: `LintContext` (`base`), `Vault.by_rel`, `Vault.get`, `parse_note_text`, `is_note_rel`, `RAW_DIR`.
- Produces (`labbrain.gitutil`): `GitError(Exception)`; frozen dataclass `Repo(top: Path, prefix: str)` with `git(*args, input=None) -> bytes`, `to_vault_rel(repo_rel) -> str | None`, property `pathspec`; `open_repo(vault_root) -> Repo | None`; `resolve_ref(repo, ref) -> str | None`; `changed_files(repo, base) -> list[tuple[str, str]]` (status letter, vault-relative path); `ls_tree(repo, base) -> dict[str, str]` (vault-relative path → blob SHA); `read_blobs(repo, shas) -> dict[str, bytes]`.
- Produces (`labbrain.lint.rules.frozen_rules`): `Policy(frozen_statuses, mutable, transitions)`; `POLICIES: dict[str, Policy]`; rule `frozen-edit` (error; `info` when skipped).

- [ ] **Step 1: Write the failing tests**

`tests/test_gitutil.py`:

```python
from __future__ import annotations

from pathlib import Path

from helpers import commit_all, git

from labbrain import gitutil


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "code"
    (repo / "brain" / "notes").mkdir(parents=True)
    (repo / "src.py").write_text("print('hi')\n")
    (repo / "brain" / "notes" / "a.md").write_text("one\n")
    (repo / "brain" / "notes" / "b.md").write_text("two\n")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo)
    return repo


def test_open_repo_reports_prefix(tmp_path: Path) -> None:
    repo_dir = make_repo(tmp_path)
    repo = gitutil.open_repo(repo_dir / "brain")
    assert repo is not None
    assert repo.top == repo_dir.resolve()
    assert repo.prefix == "brain"
    root_repo = gitutil.open_repo(repo_dir)
    assert root_repo is not None and root_repo.prefix == ""
    assert gitutil.open_repo(tmp_path) is None


def test_changed_files_tree_and_blobs_are_vault_relative(tmp_path: Path) -> None:
    repo_dir = make_repo(tmp_path)
    repo = gitutil.open_repo(repo_dir / "brain")
    assert repo is not None
    base = gitutil.resolve_ref(repo, "HEAD")
    assert base is not None and gitutil.resolve_ref(repo, "no-such-ref") is None
    (repo_dir / "src.py").write_text("print('changed')\n")
    (repo_dir / "brain" / "notes" / "a.md").write_text("one changed\n")
    (repo_dir / "brain" / "notes" / "b.md").unlink()
    assert gitutil.changed_files(repo, base) == [("M", "notes/a.md"), ("D", "notes/b.md")]
    tree = gitutil.ls_tree(repo, base)
    assert sorted(tree) == ["notes/a.md", "notes/b.md"]
    blobs = gitutil.read_blobs(repo, list(tree.values()))
    assert {blobs[tree["notes/a.md"]], blobs[tree["notes/b.md"]]} == {b"one\n", b"two\n"}
```

`tests/test_frozen.py`:

```python
from __future__ import annotations

import shutil
from pathlib import Path

from fixtures.mutations import BASELINE, EVAL_V2, IDEA_OPEN, SMOOTHING, replace
from helpers import FIXTURE, TODAY, commit_all, git

from labbrain import lint
from labbrain.sync import apply, plan
from labbrain.vault import Vault


def frozen(root: Path, base: str = "HEAD") -> list[tuple[str, str, str]]:
    findings = lint.run(Vault.load(root), today=TODAY, base=base, only=["frozen-edit"])
    return [(f.severity, f.path, f.message) for f in findings]


def test_inserting_a_section_is_allowed(vault_dir: Path) -> None:
    with (vault_dir / BASELINE).open("a") as handle:
        handle.write("\n## Postmortem\n\nNothing to add.\n")
    assert frozen(vault_dir) == []


def test_idea_move_with_allowed_transition_is_clean(vault_dir: Path) -> None:
    src = vault_dir / IDEA_OPEN
    dest = vault_dir / "ideas" / "archive" / src.name
    text = src.read_text().replace(
        "status: open", "status: consolidated\nconsolidated_into: label-smoothing-calibration"
    )
    dest.write_text(text)
    src.unlink()
    (vault_dir / "index.md").unlink()
    findings = lint.run(Vault.load(vault_dir), today=TODAY)
    assert findings == [], [f.to_dict() for f in findings]


def test_sync_output_never_trips_frozen_edit(vault_dir: Path) -> None:
    replace(
        vault_dir,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )
    commit_all(vault_dir, "supersede baseline")
    vault = Vault.load(vault_dir)
    apply(vault, plan(vault)[0], TODAY)
    findings = lint.run(Vault.load(vault_dir), today=TODAY, only=["frozen-edit", "sync-pending"])
    assert findings == []


def test_draft_protocol_referenced_by_done_experiment_is_frozen(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "status: frozen", "status: draft")
    commit_all(vault_dir, "draft protocol")
    replace(vault_dir, EVAL_V2, "ECE depends on the bin count.", "ECE is robust.")
    assert [m for _, _, m in frozen(vault_dir)] == [
        "existing body lines were modified or deleted; only insertions are allowed"
    ]


def test_draft_to_frozen_transition_is_allowed(vault_dir: Path) -> None:
    replace(vault_dir, EVAL_V2, "status: frozen", "status: draft")
    commit_all(vault_dir, "draft protocol")
    replace(vault_dir, EVAL_V2, "status: draft", "status: frozen")
    assert frozen(vault_dir) == []


def test_base_option_catches_committed_violations(vault_dir: Path) -> None:
    replace(vault_dir, BASELINE, "Try label smoothing.", "Try something else.")
    commit_all(vault_dir, "sneaky rewrite")
    assert frozen(vault_dir) == []
    assert [p for _, p, _ in frozen(vault_dir, base="HEAD~1")] == [BASELINE]


def test_skipped_outside_git_and_for_unknown_base(tmp_path: Path, vault_dir: Path) -> None:
    plain = tmp_path / "plain"
    shutil.copytree(FIXTURE, plain)
    assert frozen(plain) == [("info", "", "not a git repository; frozen-edit skipped")]
    assert frozen(vault_dir, base="no-such-ref") == [
        ("info", "", "base revision no-such-ref not found; frozen-edit skipped")
    ]


def test_subfolder_vault_ignores_code_changes(tmp_path: Path) -> None:
    repo = tmp_path / "code"
    repo.mkdir()
    (repo / "train.py").write_text("x = 1\n")
    shutil.copytree(FIXTURE, repo / "brain")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo)
    (repo / "train.py").write_text("x = 2\n")
    brain = repo / "brain"
    assert frozen(brain) == []
    replace(brain, BASELINE, "status: done", "status: running")
    assert frozen(brain) == [
        ("error", BASELINE, "status change done → running is not allowed on a frozen experiment")
    ]
```

Append to `tests/fixtures/mutations.py`:

```python
# --- frozen-edit (left uncommitted) --------------------------------------------------


@mutation("frozen-edit", commit=False)
def frozen_body_rewrite(vault: Path) -> None:
    """A done experiment's Results row is rewritten. Experiments are exempt from
    undated-fact and the frontmatter metrics are untouched."""
    replace(vault, BASELINE, "| auroc_median | 0.81 | run-001 |", "| auroc_median | 0.83 | run-001 |")


@mutation("frozen-edit", commit=False)
def frozen_status_laundering(vault: Path) -> None:
    """done → running on a frozen experiment. EVAL-v2 is still referenced by the other done
    experiment, and running evidence is not stale."""
    replace(vault, BASELINE, "status: done", "status: running")


@mutation("frozen-edit", commit=False)
def frozen_field_change(vault: Path) -> None:
    """A frozen experiment's hypothesis is rewritten."""
    replace(
        vault,
        SMOOTHING,
        'hypothesis: "Label smoothing improves calibration without lowering AUROC"',
        'hypothesis: "Label smoothing improves AUROC"',
    )


@mutation("frozen-edit", commit=False)
def frozen_handoff_deleted(vault: Path) -> None:
    """Handoffs are always frozen. Every note the handoff links to keeps another inbound link."""
    (vault / HANDOFF).unlink()


@mutation("frozen-edit", commit=False)
def frozen_raw_modified(vault: Path) -> None:
    """raw/ files are immutable."""
    with (vault / RAW_PAPER).open("a") as handle:
        handle.write("An added line.\n")


@mutation("frozen-edit", commit=False)
def frozen_idea_body_rewrite(vault: Path) -> None:
    """Ideas are create-only; rewording one is a modification."""
    replace(vault, IDEA_OPEN, "see whether late-epoch calibration holds.", "see whether it helps.")


@mutation("frozen-edit", commit=False)
def frozen_decision_retitled(vault: Path) -> None:
    """An accepted ADR's title changes."""
    replace(
        vault,
        DECISION,
        'title: "Adopt EVAL-v2 for all new experiments"',
        'title: "Adopt EVAL-v2"',
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gitutil.py tests/test_frozen.py tests/test_gate.py -v`
Expected: `ModuleNotFoundError: No module named 'labbrain.gitutil'`; the seven new gate cases fail.

- [ ] **Step 3: Implement `labbrain/gitutil.py`**

```python
"""Thin wrapper over the git CLI for reading a base revision of the vault.

All paths returned are vault-relative, so a vault living in `brain/` inside a
code repository works and code changes outside the vault are ignored.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """A git command failed."""


@dataclass(frozen=True)
class Repo:
    top: Path
    prefix: str  # vault directory inside the repo, POSIX; "" when the vault is the repo root

    def git(self, *args: str, input: bytes | None = None) -> bytes:
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.top), *args], input=input, capture_output=True, check=True
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise GitError(f"git {args[0]} failed") from exc
        return proc.stdout

    @property
    def pathspec(self) -> str:
        return self.prefix or "."

    def to_vault_rel(self, repo_rel: str) -> str | None:
        if not self.prefix:
            return repo_rel
        head = self.prefix + "/"
        return repo_rel[len(head) :] if repo_rel.startswith(head) else None


def open_repo(vault_root: Path) -> Repo | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(vault_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    top = Path(out).resolve()
    rel = vault_root.resolve().relative_to(top).as_posix()
    return Repo(top, "" if rel == "." else rel)


def resolve_ref(repo: Repo, ref: str) -> str | None:
    try:
        sha = repo.git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()
    except GitError:
        return None
    return sha or None


def changed_files(repo: Repo, base: str) -> list[tuple[str, str]]:
    """(status letter, vault-relative path) for tracked files that differ from base."""
    raw = repo.git("diff", "--name-status", "--no-renames", "-z", base, "--", repo.pathspec)
    fields = raw.decode("utf-8", "replace").split("\0")
    result = []
    for status, path in zip(fields[0::2], fields[1::2], strict=False):
        rel = repo.to_vault_rel(path) if status else None
        if rel is not None:
            result.append((status[0], rel))
    return result


def ls_tree(repo: Repo, base: str) -> dict[str, str]:
    """Vault-relative path → blob SHA for every file at base."""
    raw = repo.git("ls-tree", "-r", "-z", base, "--", repo.pathspec).decode("utf-8", "replace")
    tree = {}
    for entry in raw.split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        _mode, kind, sha = meta.split()
        rel = repo.to_vault_rel(path)
        if kind == "blob" and rel is not None:
            tree[rel] = sha
    return tree


def read_blobs(repo: Repo, shas: Iterable[str]) -> dict[str, bytes]:
    """Read many blobs through a single `git cat-file --batch` process."""
    unique = sorted(set(shas))
    if not unique:
        return {}
    out = repo.git("cat-file", "--batch", input=("\n".join(unique) + "\n").encode())
    blobs: dict[str, bytes] = {}
    pos = 0
    for _ in unique:
        newline = out.index(b"\n", pos)
        sha, _kind, size = out[pos:newline].decode().split()
        start = newline + 1
        blobs[sha] = out[start : start + int(size)]
        pos = start + int(size) + 1
    return blobs
```

- [ ] **Step 4: Implement `labbrain/lint/rules/frozen_rules.py`**

```python
"""frozen-edit: append-only notes may not be rewritten (diff against --base).

Only files git reports as changed are examined. Base versions are matched by
ID (filename), so a note moved between folders is compared, not reported as
deleted. Field values never appear in messages.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from labbrain import gitutil
from labbrain.findings import ERROR, INFO, Finding
from labbrain.layout import RAW_DIR, is_note_rel
from labbrain.lint import LintContext, rule
from labbrain.notes import Note, parse_note_text

RULE = "frozen-edit"


@dataclass(frozen=True)
class Policy:
    frozen_statuses: frozenset[str] | None  # None: frozen as soon as it exists at base
    mutable: frozenset[str]
    transitions: frozenset[tuple[str, str]]


POLICIES: dict[str, Policy] = {
    "experiment": Policy(
        frozenset({"done", "failed", "superseded"}),
        frozenset({"status", "superseded_by", "updated"}),
        frozenset({("done", "superseded"), ("failed", "superseded")}),
    ),
    "protocol": Policy(
        frozenset({"frozen", "retired"}),
        frozenset({"status", "updated"}),
        frozenset({("draft", "frozen"), ("frozen", "retired")}),
    ),
    "decision": Policy(
        frozenset({"accepted", "superseded"}),
        frozenset({"status", "superseded_by", "updated"}),
        frozenset({("accepted", "superseded")}),
    ),
    "dataset": Policy(
        None,
        frozenset({"status", "superseded_by", "updated"}),
        frozenset({("active", "superseded")}),
    ),
    "idea": Policy(
        None,
        frozenset({"status", "consolidated_into", "updated"}),
        frozenset({("open", "consolidated"), ("open", "dropped")}),
    ),
    "handoff": Policy(None, frozenset({"updated"}), frozenset()),
}


def _parse_blob(data: bytes, rel: str) -> Note:
    return parse_note_text(data.decode("utf-8", "replace"), Path(rel), rel)


class _DoneProtocolsAtBase:
    """Protocols referenced by a done experiment at base; computed only when needed."""

    def __init__(self, repo: gitutil.Repo, tree: dict[str, str]) -> None:
        self._repo, self._tree = repo, tree
        self._value: set[str] | None = None

    def get(self) -> set[str]:
        if self._value is None:
            rels = [r for r in self._tree if r.startswith("experiments/") and is_note_rel(r)]
            blobs = gitutil.read_blobs(self._repo, [self._tree[r] for r in rels])
            self._value = set()
            for rel in rels:
                note = _parse_blob(blobs[self._tree[rel]], rel)
                protocol = note.get_str("protocol")
                if note.get_str("status") == "done" and protocol:
                    self._value.add(protocol)
        return self._value


def _frozen_at_base(note: Note, policy: Policy, done_protocols: _DoneProtocolsAtBase) -> bool:
    if policy.frozen_statuses is None or note.get_str("status") in policy.frozen_statuses:
        return True
    return note.type == "protocol" and note.stem in done_protocols.get()


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _compare(base: Note, current: Note, policy: Policy) -> Iterator[Finding]:
    if base.data is None:
        return  # nothing reliable to compare against
    if current.data is None:
        yield Finding(current.rel, current.error_line, RULE, ERROR, "frozen note no longer parses")
        return
    for key in sorted(set(base.data) | set(current.data), key=str):
        if key in policy.mutable:
            continue
        if _plain(base.data.get(key)) != _plain(current.data.get(key)):
            yield Finding(current.rel, 1, RULE, ERROR, f"frozen field '{key}' changed")
    old, new = base.get_str("status"), current.get_str("status")
    if "status" in policy.mutable and old != new and (old, new) not in policy.transitions:
        message = f"status change {old} → {new} is not allowed on a frozen {base.type}"
        yield Finding(current.rel, 1, RULE, ERROR, message)
    matcher = difflib.SequenceMatcher(
        None, base.body.splitlines(), current.body.splitlines(), autojunk=False
    )
    for tag, _i1, _i2, j1, _j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            message = "existing body lines were modified or deleted; only insertions are allowed"
            yield Finding(current.rel, current.body_line + j1, RULE, ERROR, message)


@rule(RULE, ERROR, "Frozen notes changed outside allowed fields, deleted, or raw/ files edited")
def frozen_edit(ctx: LintContext) -> Iterator[Finding]:
    repo = gitutil.open_repo(ctx.vault.root)
    if repo is None:
        yield Finding("", 0, RULE, INFO, "not a git repository; frozen-edit skipped")
        return
    base = gitutil.resolve_ref(repo, ctx.base)
    if base is None:
        message = f"base revision {ctx.base} not found; frozen-edit skipped"
        yield Finding("", 0, RULE, INFO, message)
        return
    changes = gitutil.changed_files(repo, base)
    for status, rel in changes:
        if rel.startswith(f"{RAW_DIR}/"):
            verb = "deleted" if status == "D" else "modified"
            yield Finding(rel, 0, RULE, ERROR, f"raw/ files are immutable; this file was {verb}")
    note_changes = [(s, rel) for s, rel in changes if s in ("M", "D", "T") and is_note_rel(rel)]
    if not note_changes:
        return
    tree = gitutil.ls_tree(repo, base)
    blobs = gitutil.read_blobs(repo, [tree[rel] for _, rel in note_changes if rel in tree])
    done_protocols = _DoneProtocolsAtBase(repo, tree)
    for status, rel in note_changes:
        if rel not in tree:
            continue
        base_note = _parse_blob(blobs[tree[rel]], rel)
        policy = POLICIES.get(base_note.type or "")
        if policy is None or not _frozen_at_base(base_note, policy, done_protocols):
            continue
        current = ctx.vault.get(base_note.stem) if status == "D" else ctx.vault.by_rel.get(rel)
        if current is None:
            message = f"frozen {base_note.type} {base_note.stem} was deleted; supersede it instead"
            yield Finding(rel, 0, RULE, ERROR, message)
            continue
        yield from _compare(base_note, current, policy)
```

Note: the handoff policy has no mutable `status`, so a status change on a handoff is reported once, as a frozen-field change.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_gitutil.py tests/test_frozen.py tests/test_gate.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, and every earlier gate case still fires only its own rule (they are committed, so `frozen-edit` sees no diff).

- [ ] **Step 6: Commit**

```bash
git add labbrain/gitutil.py labbrain/lint/rules/frozen_rules.py tests
git commit -m "feat(lint): frozen-edit rule with diff-driven, batched git reads" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: PHI scanner, allowlist, `phi` rule, and PHI in `validate`

**Files:**
- Create: `labbrain/phi.py`, `labbrain/lint/rules/phi_rules.py`
- Modify: `labbrain/validate.py`, `tests/fixtures/mutations.py` (append)
- Test: `tests/test_phi.py`

**Interfaces:**
- Consumes: `Config`, `ConfigError`, `Finding`, `sort_findings`, `ALLOWLIST_PATH`, `PHI_SKIP_DIR_NAMES`, `PHI_SKIP_FILES`, `INDEX_FILE`.
- Produces (`labbrain.phi`): `PhiHit(rule, line, col, length, line_sha)`; `ScanSettings(min_cell_size=11, mrn_regex=None, denylist=None)` with classmethod `from_config(config, root)`; `line_hash(line) -> str` (first 16 hex chars of sha256 of the stripped line); `scan_text(text, settings) -> list[PhiHit]`; `is_binary(path) -> bool`; `iter_scan_files(base) -> Iterator[Path]`; `in_scan_scope(rel) -> bool`; `load_denylist(root, rel_path)`; `AllowlistError(ConfigError)`; `load_allowlist(root) -> frozenset[tuple[str, str, str]]`; `scan(paths, *, root, settings, allow, rule_name=None) -> list[Finding]` (`rule_name=None`: each pattern is its own rule, as in `labbrain phi-scan`; `"phi"`: re-badged for lint and validate).
- Produces: rule `phi` (error). Rule names emitted by the scanner: `phi-mrn`, `phi-date`, `phi-phone`, `phi-email`, `phi-ssn`, `phi-address`, `phi-name`, `phi-small-cell`.

- [ ] **Step 1: Write the failing tests**

`tests/test_phi.py`:

```python
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
    text = (
        "| group | n | seeds |\n"
        "|---|---|---|\n"
        "| a | 4 | 3 |\n"
        "| b | 40 | 2 |\n"
        "| c | <11 | 1 |\n"
    )
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
```

Append to `tests/fixtures/mutations.py` (add `import random` to the imports at the top):

```python
# --- phi -----------------------------------------------------------------------------

_RNG = random.Random(4242)


def _synthetic_phone() -> str:
    return f"{_RNG.randrange(200, 999)}-555-{_RNG.randrange(1000, 9999)}"


@mutation("phi")
def phi_phone_in_concept(vault: Path) -> None:
    """A synthetic phone number in the concept; the line has no metric-like number."""
    replace(
        vault,
        CONCEPT,
        "## Open questions\n\n",
        f"## Open questions\n\nAsk the data steward at {_synthetic_phone()} about access.\n\n",
    )


@mutation("phi")
def phi_small_cell_in_dataset(vault: Path) -> None:
    """A dataset reports a count below min_cell_size (committed, so no frozen-edit)."""
    replace(
        vault,
        DATASET,
        "All images; no filtering.",
        "All images; no filtering. Excluded: n = 4 patients.",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_phi.py tests/test_gate.py -v`
Expected: `ModuleNotFoundError: No module named 'labbrain.phi'`; the two new gate cases fail.

- [ ] **Step 3: Implement `labbrain/phi.py`**

```python
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
    names = [
        line.strip()
        for line in (root / rel_path).read_text(encoding="utf-8").splitlines()
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
            hits.append(PhiHit(rule_name, lineno, start + 1, end - start, line_hash(lines[lineno - 1])))

    for lineno, line in enumerate(lines, start=1):
        for rule_name, start, end in _line_spans(line, settings):
            add(rule_name, lineno, start, end)
    for lineno, start, end in _table_small_cells(lines, settings.min_cell_size):
        add("phi-small-cell", lineno, start, end)
    return sorted(hits, key=lambda h: (h.line, h.col, h.rule))


def is_binary(path: Path) -> bool:
    if path.suffix.lower() == ".pdf":
        return True
    with path.open("rb") as handle:
        return b"\0" in handle.read(8192)


def in_scan_scope(rel: str) -> bool:
    """False for paths phi-scan never reads: dot-directories, skip dirs, index.md."""
    parts = PurePosixPath(rel).parts
    if rel == INDEX_FILE:
        return False
    return not any(p.startswith(".") or p in PHI_SKIP_DIR_NAMES for p in parts[:-1])


def iter_scan_files(base: Path) -> Iterator[Path]:
    if base.is_file():
        if not is_binary(base):
            yield base
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in PHI_SKIP_DIR_NAMES
        )
        here = Path(dirpath)
        for name in sorted(filenames):
            if here == base and name in PHI_SKIP_FILES:
                continue
            path = here / name
            if path.is_file() and not is_binary(path):
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
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def scan(
    paths: Iterable[Path],
    *,
    root: Path | None,
    settings: ScanSettings,
    allow: frozenset[tuple[str, str, str]],
    rule_name: str | None = None,
) -> list[Finding]:
    findings = []
    for base in paths:
        for path in iter_scan_files(base):
            rel = _rel(path, root)
            text = path.read_text(encoding="utf-8", errors="replace")
            for hit in scan_text(text, settings):
                if (rel, hit.rule, hit.line_sha) in allow:
                    continue
                span = f"(span: {hit.length} chars)"
                message = span if rule_name is None else f"{hit.rule} {span}"
                findings.append(
                    Finding(rel, hit.line, rule_name or hit.rule, ERROR, message, col=hit.col)
                )
    return sort_findings(findings)
```

- [ ] **Step 4: Implement `labbrain/lint/rules/phi_rules.py`**

```python
"""phi: PHI scan findings not covered by the allowlist (protected projects only)."""

from __future__ import annotations

from collections.abc import Iterator

from labbrain import phi as phi_scan
from labbrain.findings import ERROR, Finding
from labbrain.lint import LintContext, rule


@rule("phi", ERROR, "phi-scan findings not in the allowlist (protected projects only)")
def phi(ctx: LintContext) -> Iterator[Finding]:
    config = ctx.vault.config
    if not config.protected_data:
        return
    root = ctx.vault.root
    yield from phi_scan.scan(
        [root],
        root=root,
        settings=phi_scan.ScanSettings.from_config(config, root),
        allow=phi_scan.load_allowlist(root),
        rule_name="phi",
    )
```

- [ ] **Step 5: Add PHI to `labbrain/validate.py`**

In `validate_path`, replace

```python
    if is_note_rel(rel):
        findings.extend(_check_note_file(target, root, config))
    return sort_findings(findings)
```

with

```python
    if is_note_rel(rel):
        findings.extend(_check_note_file(target, root, config))
    if config.protected_data:
        from labbrain.phi import ScanSettings, in_scan_scope, load_allowlist, scan

        if in_scan_scope(rel):
            findings.extend(
                scan(
                    [target],
                    root=root,
                    settings=ScanSettings.from_config(config, root),
                    allow=load_allowlist(root),
                    rule_name="phi",
                )
            )
    return sort_findings(findings)
```

and update the module docstring's last sentence to: "It parses one note, checks it against the config, finds duplicate filenames with a directory walk, and scans the file for PHI when the project is protected."

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_phi.py tests/test_validate.py tests/test_gate.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; the valid fixture is still clean with `phi` active.

- [ ] **Step 7: Commit**

```bash
git add labbrain/phi.py labbrain/lint/rules/phi_rules.py labbrain/validate.py tests
git commit -m "feat(phi): context-aware PHI scanner, line-hash allowlist, phi rule" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Skeleton notes, graph queries and config hashing

**Files:**
- Create: `labbrain/scaffold.py`, `labbrain/query.py`, `labbrain/confighash.py`
- Test: `tests/test_scaffold.py`, `tests/test_query.py`, `tests/test_confighash.py`

**Interfaces:**
- Consumes: `new_id`, `protocol_version`, `TYPE_FOLDERS`, `atomic_write`, `render_note`, `DEFAULT_STATUS`, `REQUIRED_SECTIONS`, `FUTURE_AGENTS_HEADING`, `Config`, `Vault`.
- Produces (`labbrain.scaffold`): `TYPE_FIELDS: dict[str, dict[str, Any]]`; `skeleton(note_type, *, note_id, title, author, now, config, links=(), extra=None) -> str`; `create(root, config, note_type, *, title, author, now, links=(), agent="", first_author="", year=None, name="") -> Path`.
- Produces (`labbrain.query`): `list_notes(vault, *, note_type=None, status=None, tag=None) -> list[dict]` (keys `id`, `type`, `status`, `title`, `created`, `path`; sorted by ID); `links(vault, note_id) -> dict` (keys `id`, `in`, `out`; raises `KeyError` for unknown IDs).
- Produces (`labbrain.confighash`): `flatten(config, prefix="") -> dict`; `config_hash(config, ignore) -> str` (`"sha256:<64 hex>"`); `load_run_config(path) -> dict` (raises `ValueError` on unreadable or non-mapping input).

- [ ] **Step 1: Write the failing tests**

`tests/test_scaffold.py`:

```python
from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path

import pytest
from helpers import make_vault

from labbrain.layout import NOTE_TYPES, TYPE_FOLDERS
from labbrain.notes import update_frontmatter
from labbrain.scaffold import create
from labbrain.validate import validate_path
from labbrain.vault import load_config

NOW = datetime(2026, 10, 15, 12, 0)

EXPECTED_EXPERIMENT = """---
id: EXP-20261015-label-smoothing
type: experiment
title: Label smoothing
created: 2026-10-15
updated: 2026-10-15
author: alice
status: planned
tags: []
links: []
hypothesis:
protocol:
tracker:
code:
config_hash:
dataset:
metrics: []
supersedes:
superseded_by:
---
## Hypothesis

## Setup

## Results

## Interpretation

## Next
"""


def test_experiment_skeleton_text(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    path = create(root, load_config(root), "experiment", title="Label smoothing", author="alice", now=NOW)
    assert path == root / "experiments" / "EXP-20261015-label-smoothing.md"
    assert path.read_text() == EXPECTED_EXPERIMENT


@pytest.mark.parametrize("author", ["alice", "claude"])
@pytest.mark.parametrize("note_type", NOTE_TYPES)
def test_every_skeleton_validates_clean(vault_dir: Path, note_type: str, author: str) -> None:
    path = create(
        vault_dir,
        load_config(vault_dir),
        note_type,
        title="A new thing",
        author=author,
        now=NOW,
        first_author="Doe",
        year=2024,
    )
    assert path.parent == vault_dir / TYPE_FOLDERS[note_type]
    assert validate_path(path) == []


def test_protocol_skeleton_gets_next_version(vault_dir: Path) -> None:
    path = create(vault_dir, load_config(vault_dir), "protocol", title="Masked AUROC", author="alice", now=NOW)
    assert path.name == "EVAL-v3.md"
    assert "version: 3\n" in path.read_text()


def test_agent_skeleton_has_future_agents_block(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    path = create(root, load_config(root), "idea", title="Try it", author="claude", now=NOW)
    body = path.read_text().split("---\n", 2)[2]
    assert body.startswith("## For future agents\n\n<!-- ")


def test_skeleton_edits_are_one_line_diffs(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    path = create(root, load_config(root), "experiment", title="X", author="alice", now=NOW)
    before = path.read_text()
    update_frontmatter(path, {"status": "running"})
    changed = [
        line
        for line in difflib.ndiff(before.splitlines(), path.read_text().splitlines())
        if line.startswith(("+ ", "- "))
    ]
    assert changed == ["- status: planned", "+ status: running"]
```

`tests/test_query.py`:

```python
from __future__ import annotations

import pytest
from helpers import FIXTURE

from labbrain.query import links, list_notes
from labbrain.vault import Vault


def test_list_filters() -> None:
    vault = Vault.load(FIXTURE)
    assert [r["id"] for r in list_notes(vault, note_type="experiment")] == [
        "EXP-20260901-baseline",
        "EXP-20260910-label-smoothing",
    ]
    assert [r["id"] for r in list_notes(vault, note_type="idea", status="open")] == [
        "IDEA-20261010-smoothing-schedule"
    ]
    assert [r["id"] for r in list_notes(vault, tag="evaluation")] == [
        "ADR-20260905-adopt-eval-v2",
        "EVAL-v1",
        "EVAL-v2",
    ]
    row = list_notes(vault, note_type="claim")[0]
    assert row == {
        "id": "CLM-20261001-median-auroc",
        "type": "claim",
        "status": "supported",
        "title": "Median AUROC of the baseline",
        "created": "2026-10-01",
        "path": "claims/CLM-20261001-median-auroc.md",
    }


def test_links() -> None:
    vault = Vault.load(FIXTURE)
    assert links(vault, "CLM-20261001-median-auroc") == {
        "id": "CLM-20261001-median-auroc",
        "in": ["HO-20261014-1420-claude", "label-smoothing-calibration"],
        "out": ["EVAL-v2", "EXP-20260901-baseline"],
    }
    with pytest.raises(KeyError):
        links(vault, "nope")
```

`tests/test_confighash.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from labbrain.confighash import config_hash, flatten, load_run_config
from labbrain.vault import DEFAULT_HASH_IGNORE


def test_flatten() -> None:
    assert flatten({"a": {"b": 1, "c": {"d": 2}}, "e": [1, 2], "f": {}}) == {
        "a.b": 1,
        "a.c.d": 2,
        "e": [1, 2],
        "f": {},
    }


def test_hash_ignores_key_order_and_nesting_style() -> None:
    nested = {"train": {"lr": 0.001, "epochs": 10}, "model": "resnet"}
    dotted = {"model": "resnet", "train.epochs": 10, "train.lr": 0.001}
    assert config_hash(nested, []) == config_hash(dotted, [])


def test_hash_ignore_patterns() -> None:
    first = {"train": {"lr": 0.001, "seed": 1}, "seed": 7, "output_dir": "/tmp/a"}
    second = {"train": {"lr": 0.001, "seed": 2}, "seed": 8, "output_dir": "/tmp/b"}
    assert config_hash(first, DEFAULT_HASH_IGNORE) == config_hash(second, DEFAULT_HASH_IGNORE)
    assert config_hash(first, []) != config_hash(second, [])


def test_value_change_changes_hash_and_format() -> None:
    a = config_hash({"lr": 0.001}, [])
    b = config_hash({"lr": 0.002}, [])
    assert a != b
    assert a.startswith("sha256:") and len(a) == len("sha256:") + 64


def test_load_run_config(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("train:\n  lr: 0.001\n")
    (tmp_path / "c.json").write_text(json.dumps({"train": {"lr": 0.001}}))
    assert load_run_config(tmp_path / "c.yaml") == load_run_config(tmp_path / "c.json")
    (tmp_path / "bad.yaml").write_text("- a\n")
    with pytest.raises(ValueError):
        load_run_config(tmp_path / "bad.yaml")
    with pytest.raises(ValueError):
        load_run_config(tmp_path / "missing.yaml")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scaffold.py tests/test_query.py tests/test_confighash.py -v`
Expected: `ModuleNotFoundError` for `labbrain.scaffold`, `labbrain.query`, `labbrain.confighash`.

- [ ] **Step 3: Implement `labbrain/scaffold.py`**

```python
"""Skeleton notes for `labbrain new`, generated from the schema registries.

Every skeleton passes `labbrain validate` with zero findings, so skills fill in
a valid note instead of writing frontmatter by hand, and IDs are always minted
by the tool.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labbrain.ids import new_id, protocol_version
from labbrain.layout import TYPE_FOLDERS
from labbrain.notes import atomic_write, render_note
from labbrain.schema import DEFAULT_STATUS, FUTURE_AGENTS_HEADING, REQUIRED_SECTIONS
from labbrain.vault import Config

FUTURE_AGENTS_PLACEHOLDER = (
    "<!-- Up to three lines: what this note is, what is safe to rely on, what to check first. -->"
)

# Type-specific fields in display order. A list default renders as a flow list (`[]`).
TYPE_FIELDS: dict[str, dict[str, Any]] = {
    "experiment": {
        "hypothesis": None,
        "protocol": None,
        "tracker": None,
        "code": None,
        "config_hash": None,
        "dataset": None,
        "metrics": [],
        "supersedes": None,
        "superseded_by": None,
    },
    "protocol": {"version": None, "changes_from": None, "comparable_with": []},
    "claim": {
        "statement": None,
        "value": None,
        "value_format": None,
        "tolerance": None,
        "evidence": [],
        "protocol": None,
        "manuscript_locations": [],
    },
    "idea": {"consolidated_into": None},
    "concept": {"sources": []},
    "decision": {"supersedes": None, "superseded_by": None},
    "literature": {
        "doi": None,
        "arxiv": None,
        "url": None,
        "year": None,
        "venue": None,
        "relevance": None,
    },
    "handoff": {"agent": None, "session_goal": None, "files_touched": []},
    "dataset": {
        "location": None,
        "extracted": None,
        "split_of": None,
        "counts": None,
        "protected": None,
        "supersedes": None,
        "superseded_by": None,
    },
}


def _flow(items: Iterable[Any]) -> CommentedSeq:
    seq = CommentedSeq(list(items))
    seq.fa.set_flow_style()
    return seq


def skeleton(
    note_type: str,
    *,
    note_id: str,
    title: str,
    author: str,
    now: datetime,
    config: Config,
    links: Iterable[str] = (),
    extra: Mapping[str, Any] | None = None,
) -> str:
    data = CommentedMap()
    data["id"] = note_id
    data["type"] = note_type
    data["title"] = title
    data["created"] = now.date()
    data["updated"] = now.date()
    data["author"] = author
    data["status"] = DEFAULT_STATUS[note_type]
    data["tags"] = _flow([])
    data["links"] = _flow(links)
    for key, default in TYPE_FIELDS[note_type].items():
        data[key] = _flow(default) if isinstance(default, list) else default
    for key, value in (extra or {}).items():
        data[key] = value
    sections = []
    if config.is_agent(author):
        sections.append(f"## {FUTURE_AGENTS_HEADING}\n\n{FUTURE_AGENTS_PLACEHOLDER}\n")
    sections += [f"## {section}\n" for section in REQUIRED_SECTIONS[note_type]]
    return render_note(data, "\n".join(sections))


def create(
    root: Path,
    config: Config,
    note_type: str,
    *,
    title: str,
    author: str,
    now: datetime,
    links: Iterable[str] = (),
    agent: str = "",
    first_author: str = "",
    year: int | None = None,
    name: str = "",
) -> Path:
    agent = agent or author
    note_id = new_id(
        note_type,
        root=root,
        now=now,
        title=title,
        prefixes=config.id_prefixes,
        agent=agent,
        first_author=first_author,
        year=year,
        name=name,
    )
    extra: dict[str, Any] = {}
    if note_type == "protocol":
        extra["version"] = protocol_version(note_id, config.id_prefixes)
    elif note_type == "handoff":
        extra["agent"] = agent
    elif note_type == "literature":
        extra["year"] = year
    path = root / TYPE_FOLDERS[note_type] / f"{note_id}.md"
    text = skeleton(
        note_type,
        note_id=note_id,
        title=title,
        author=author,
        now=now,
        config=config,
        links=links,
        extra=extra,
    )
    atomic_write(path, text)
    return path
```

- [ ] **Step 4: Implement `labbrain/query.py`**

```python
"""Read-only graph queries for skills and non-Claude agents (`list`, `links`)."""

from __future__ import annotations

from typing import Any

from labbrain.vault import Vault


def list_notes(
    vault: Vault,
    *,
    note_type: str | None = None,
    status: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for stem in sorted(vault.notes):
        note = vault.notes[stem]
        if note_type and note.type != note_type:
            continue
        if status and note.get_str("status") != status:
            continue
        if tag and tag not in note.get_list("tags"):
            continue
        created = note.get_date("created")
        rows.append(
            {
                "id": stem,
                "type": note.type,
                "status": note.get_str("status"),
                "title": note.get_str("title"),
                "created": created.isoformat() if created else None,
                "path": note.rel,
            }
        )
    return rows


def links(vault: Vault, note_id: str) -> dict[str, Any]:
    if note_id not in vault.notes:
        raise KeyError(note_id)
    return {
        "id": note_id,
        "in": sorted(vault.inbound.get(note_id, set())),
        "out": sorted(vault.outbound.get(note_id, set())),
    }
```

- [ ] **Step 5: Implement `labbrain/confighash.py`**

```python
"""config_hash: SHA-256 over the flattened run config, minus hash_ignore keys.

Implemented now (before /exp-log exists) so every caller hashes identically
and duplicate-config compares like with like.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from labbrain.notes import safe_load


def flatten(config: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in config.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            flat.update(flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def config_hash(config: Mapping[str, Any], ignore: Iterable[str]) -> str:
    patterns = list(ignore)
    kept = {
        key: value
        for key, value in flatten(config).items()
        if not any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)
    }
    payload = json.dumps(kept, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_run_config(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix == ".json" else safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read run config {path.name}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"run config {path.name} must be a mapping")
    return data
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_scaffold.py tests/test_query.py tests/test_confighash.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass. If `test_experiment_skeleton_text` differs only in how ruamel renders empty values, update `EXPECTED_EXPERIMENT` to ruamel's actual output; the binding requirements are that every skeleton validates clean and that a one-field edit is a one-line diff.

- [ ] **Step 7: Commit**

```bash
git add labbrain/scaffold.py labbrain/query.py labbrain/confighash.py tests
git commit -m "feat: skeleton notes, graph queries and config hashing" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Command line

**Files:**
- Create: `labbrain/cli.py`, `labbrain/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above. Library calls only; no logic in the CLI.
- Produces: `labbrain.cli.main(argv: list[str] | None = None) -> int`; `labbrain.cli.run() -> None` (console-script entry point); `python -m labbrain`. Subcommands and options exactly as in spec section 6, plus global `--vault PATH` and `--version`. Exit codes `0`/`1`/`2`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest
from fixtures.mutations import BASELINE, CONCEPT, SMOOTHING, replace
from helpers import MIN_CONFIG, make_vault

from labbrain import __version__
from labbrain.cli import main


@pytest.fixture(autouse=True)
def _no_author_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_AUTHOR", raising=False)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert capsys.readouterr().out.strip() == f"labbrain {__version__}"


def test_vault_root_discovery_and_explicit_vault(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run(capsys, "vault", "root") == (0, f"{vault_dir.resolve()}\n", "")
    monkeypatch.delenv("LABBRAIN_VAULT")
    monkeypatch.chdir(vault_dir.parent)
    code, _, err = run(capsys, "vault", "root")
    assert code == 2 and "no vault found" in err
    code, out, _ = run(capsys, "--vault", str(vault_dir), "vault", "root")
    assert (code, out.strip()) == (0, str(vault_dir.resolve()))
    code, out, _ = run(capsys, "lint", "--vault", str(vault_dir))
    assert (code, out) == (0, "0 error(s), 0 warning(s), 0 info\n")


def test_config(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "config", "--key", "tracker.backend")[1] == "local\n"
    code, out, _ = run(capsys, "config")
    assert code == 0 and json.loads(out)["project_slug"] == "toy-classifier"
    assert run(capsys, "config", "--key", "nope")[0] == 2


def test_new_id_and_new(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "new-id", "experiment", "--title", "Label smoothing v2")
    assert (code, out) == (0, "EXP-20261015-label-smoothing-v2\n")
    assert run(capsys, "new-id", "experiment")[0] == 2
    code, out, _ = run(capsys, "new", "decision", "--title", "Pick a tracker", "--author", "alice")
    path = Path(out.strip())
    assert code == 0
    assert path == vault_dir.resolve() / "decisions" / "ADR-20261015-pick-a-tracker.md"
    assert run(capsys, "validate", str(path))[0] == 0
    assert run(capsys, "new", "decision", "--title", "x")[0] == 2
    assert run(capsys, "new", "literature", "--title", "x", "--author", "bob")[0] == 2


def test_validate_exit_codes_and_json(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "validate", str(vault_dir / CONCEPT), "--json")
    assert code == 0 and json.loads(out)["findings"] == []
    replace(vault_dir, CONCEPT, "status: active", "status: archived")
    code, out, _ = run(capsys, "validate", str(vault_dir / CONCEPT), "--json")
    assert code == 1
    assert [f["rule"] for f in json.loads(out)["findings"]] == ["schema"]


def test_lint(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "lint") == (0, "0 error(s), 0 warning(s), 0 info\n", "")
    replace(vault_dir, BASELINE, "status: done", "status: running")
    code, out, _ = run(capsys, "lint", "--format", "github")
    assert code == 1
    assert out.startswith(
        "::error file=experiments/EXP-20260901-baseline.md,line=1,title=frozen-edit::"
    )
    assert run(capsys, "lint", "--rule", "orphan")[0] == 0
    code, _, err = run(capsys, "lint", "--rule", "nope")
    assert code == 2 and "unknown lint rule" in err


def test_sync(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    replace(
        vault_dir,
        SMOOTHING,
        "links: [EXP-20260901-baseline]",
        "links: [EXP-20260901-baseline]\nsupersedes: EXP-20260901-baseline",
    )
    code, out, _ = run(capsys, "sync", "--dry-run")
    assert code == 0 and "would update" in out
    assert "status: done" in (vault_dir / BASELINE).read_text()
    code, out, _ = run(capsys, "sync")
    assert code == 0 and "updated:" in out
    assert "status: superseded" in (vault_dir / BASELINE).read_text()
    assert json.loads(run(capsys, "sync", "--json")[1])["findings"] == []


def test_index_and_log(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "index", "--check")[0] == 0
    replace(vault_dir, CONCEPT, 'title: "Label smoothing and calibration"', 'title: "Renamed"')
    assert run(capsys, "index", "--check")[0] == 1
    assert run(capsys, "index")[1] == "index.md updated\n"
    assert run(capsys, "index", "--check")[0] == 0
    code, out, _ = run(capsys, "log", "exp-log: logged a run", "--author", "alice")
    assert code == 0
    assert Path(out.strip()).read_text().endswith("- 12:00 [alice] exp-log: logged a run\n")


def test_phi_outputs_never_echo_identifiers(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    value = str(random.Random(7).randrange(10_000_000, 99_999_999))
    path = vault_dir / "manuscripts" / "draft.md"
    path.parent.mkdir()
    path.write_text(f"Patient MRN {value}.\n")
    for args in (
        ("phi-scan", str(path)),
        ("phi-scan", str(vault_dir), "--json"),
        ("validate", str(path), "--format", "github"),
        ("lint", "--json"),
    ):
        code, out, err = run(capsys, *args)
        assert code == 1, args
        assert value not in out + err, args


def test_phi_scan_outside_a_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)
    (tmp_path / "notes.md").write_text("n = 4 patients\n")
    code, out, _ = run(capsys, "phi-scan", str(tmp_path))
    assert code == 1 and "[phi-small-cell]" in out
    assert run(capsys, "phi-scan", str(tmp_path / "missing"))[0] == 2


def test_list_links_config_hash_schema(
    vault_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "list", "--type", "experiment", "--json")
    assert code == 0
    assert [r["id"] for r in json.loads(out)] == [
        "EXP-20260901-baseline",
        "EXP-20260910-label-smoothing",
    ]
    assert run(capsys, "links", "CLM-20261001-median-auroc", "--in")[1] == (
        "in\tHO-20261014-1420-claude\nin\tlabel-smoothing-calibration\n"
    )
    assert run(capsys, "links", "nope")[0] == 2
    run_config = tmp_path / "run.yaml"
    run_config.write_text("train:\n  lr: 0.001\n  seed: 3\n")
    code, out, _ = run(capsys, "config-hash", str(run_config))
    assert code == 0 and out.startswith("sha256:")
    assert json.loads(run(capsys, "schema", "claim")[1])["title"] == "ClaimNote"


def test_config_problems_exit_2_and_version_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = make_vault(tmp_path / "bad", MIN_CONFIG + "min_cell_size: 1\n")
    monkeypatch.setenv("LABBRAIN_VAULT", str(bad))
    code, _, err = run(capsys, "lint")
    assert code == 2 and "min_cell_size" in err
    newer = make_vault(tmp_path / "newer", MIN_CONFIG + "engine_min_version: 99.0.0\n")
    monkeypatch.setenv("LABBRAIN_VAULT", str(newer))
    _, _, err = run(capsys, "lint")
    assert "engine_min_version 99.0.0" in err


def test_cli_import_is_lightweight() -> None:
    probe = (
        "import sys, labbrain.cli; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('pydantic', 'ruamel', 'yaml')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[]"


def test_module_entry_point() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "labbrain", "--version"], capture_output=True, text=True
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"labbrain {__version__}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: `ModuleNotFoundError: No module named 'labbrain.cli'`.

- [ ] **Step 3: Implement `labbrain/cli.py`**

```python
"""`labbrain` command line: parse arguments, call the library, format output.

Only the standard library and labbrain.layout are imported at module level;
everything else is imported inside the command that needs it, because the
lab-brain hooks call this CLI on every tool use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from labbrain import __version__
from labbrain.layout import NOTE_TYPES

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2


class UsageError(Exception):
    """Reported on stderr with exit code 2."""


# --- helpers ----------------------------------------------------------------------


def _root(args: argparse.Namespace) -> Path:
    from labbrain.vault import find_root

    return find_root(explicit=args.vault)


def _warn_version(config: Any) -> None:
    from labbrain.vault import version_warning

    warning = version_warning(config)
    if warning:
        print(f"labbrain: warning: {warning}", file=sys.stderr)


def _config(args: argparse.Namespace) -> tuple[Path, Any]:
    from labbrain.vault import load_config

    root = _root(args)
    config = load_config(root)
    _warn_version(config)
    return root, config


def _vault(args: argparse.Namespace) -> Any:
    from labbrain.vault import Vault

    root, config = _config(args)
    return Vault.load(root, config)


def _emit(findings: list[Any], fmt: str) -> int:
    from labbrain.findings import exit_code, render

    output = render(findings, fmt)
    if output:
        print(output)
    return exit_code(findings)


def _now(at: str | None) -> datetime:
    from labbrain.vault import now

    if not at:
        return now()
    try:
        return datetime.fromisoformat(at)
    except ValueError as exc:
        raise UsageError("--at must be an ISO datetime") from exc


def _author(args: argparse.Namespace) -> str:
    author = args.author or os.environ.get("LABBRAIN_AUTHOR")
    if not author:
        raise UsageError("--author is required (or set LABBRAIN_AUTHOR)")
    return author


# --- commands ---------------------------------------------------------------------


def cmd_vault_root(args: argparse.Namespace) -> int:
    print(_root(args))
    return EXIT_OK


def cmd_config(args: argparse.Namespace) -> int:
    _, config = _config(args)
    data: Any = config.model_dump(mode="json")
    if args.key:
        for part in args.key.split("."):
            if not isinstance(data, dict) or part not in data:
                raise UsageError(f"no config key {args.key}")
            data = data[part]
        print(data if isinstance(data, str) else json.dumps(data))
    else:
        print(json.dumps(data, indent=2))
    return EXIT_OK


def cmd_new_id(args: argparse.Namespace) -> int:
    from labbrain.ids import IdError, new_id

    if args.type not in ("protocol", "handoff") and not args.title:
        raise UsageError(f"--title is required for {args.type} IDs")
    root, config = _config(args)
    try:
        note_id = new_id(
            args.type,
            root=root,
            now=_now(args.at),
            title=args.title,
            prefixes=config.id_prefixes,
            agent=args.agent or args.author or "",
            first_author=args.first_author,
            year=args.year,
            name=args.name,
        )
    except IdError as exc:
        raise UsageError(str(exc)) from exc
    print(note_id)
    return EXIT_OK


def cmd_new(args: argparse.Namespace) -> int:
    from labbrain.ids import IdError
    from labbrain.scaffold import create

    if not args.title:
        raise UsageError("--title is required")
    author = _author(args)
    root, config = _config(args)
    try:
        path = create(
            root,
            config,
            args.type,
            title=args.title,
            author=author,
            now=_now(args.at),
            links=args.link,
            agent=args.agent,
            first_author=args.first_author,
            year=args.year,
            name=args.name,
        )
    except IdError as exc:
        raise UsageError(str(exc)) from exc
    print(path)
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    from labbrain.validate import validate_paths

    return _emit(validate_paths(args.paths, vault=args.vault), args.format)


def cmd_sync(args: argparse.Namespace) -> int:
    from labbrain.findings import ERROR, INFO, Finding, sort_findings
    from labbrain.sync import apply, plan
    from labbrain.vault import today

    vault = _vault(args)
    changes, conflicts = plan(vault)
    if not args.dry_run:
        apply(vault, changes, today())
    verb = "would update" if args.dry_run else "updated"
    findings = [Finding(c.rel, 1, "sync", ERROR, c.message) for c in conflicts]
    for change in changes:
        fields = ", ".join(f"{key} → {value}" for key, value in change.updates.items())
        findings.append(Finding(change.rel, 1, "sync", INFO, f"{verb}: {fields} ({change.reason})"))
    return _emit(sort_findings(findings), args.format)


def cmd_index(args: argparse.Namespace) -> int:
    from labbrain.index import is_stale, write

    vault = _vault(args)
    if args.check:
        stale = is_stale(vault)
        if stale is None:
            print("index.md is missing; run `labbrain index`")
            return EXIT_FINDINGS
        if stale:
            print("index.md is out of date; run `labbrain index`")
            return EXIT_FINDINGS
        print("index.md is up to date")
        return EXIT_OK
    print("index.md updated" if write(vault) else "index.md already up to date")
    return EXIT_OK


def cmd_log(args: argparse.Namespace) -> int:
    from labbrain.log import append
    from labbrain.vault import now

    try:
        path = append(_root(args), args.text, when=now(), author=args.author)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    print(path)
    return EXIT_OK


def cmd_lint(args: argparse.Namespace) -> int:
    from labbrain import lint

    vault = _vault(args)
    try:
        findings = lint.run(vault, base=args.base, only=args.rule or None)
    except lint.UnknownRuleError as exc:
        raise UsageError(str(exc)) from exc
    return _emit(findings, args.format)


def cmd_phi_scan(args: argparse.Namespace) -> int:
    from labbrain.phi import ScanSettings, load_allowlist, scan
    from labbrain.vault import VaultNotFound, default_config, find_root, load_config

    paths = [p.expanduser().resolve() for p in args.paths]
    for path in paths:
        if not path.exists():
            raise UsageError(f"no such file or directory: {path.name}")
    start = paths[0] if paths[0].is_dir() else paths[0].parent
    try:
        root: Path | None = find_root(start=start, explicit=args.vault)
        config = load_config(root)
    except VaultNotFound:
        root, config = None, default_config()
    settings = ScanSettings.from_config(config, root)
    return _emit(scan(paths, root=root, settings=settings, allow=load_allowlist(root)), args.format)


def cmd_list(args: argparse.Namespace) -> int:
    from labbrain.query import list_notes

    rows = list_notes(_vault(args), note_type=args.note_type, status=args.status, tag=args.tag)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['id']}\t{row['type']}\t{row['status'] or ''}\t{row['title'] or ''}")
    return EXIT_OK


def cmd_links(args: argparse.Namespace) -> int:
    from labbrain.query import links

    try:
        data = links(_vault(args), args.id)
    except KeyError as exc:
        raise UsageError(f"no note with ID {args.id}") from exc
    directions = [args.direction] if args.direction else ["in", "out"]
    if args.json:
        print(json.dumps({"id": data["id"], **{d: data[d] for d in directions}}, indent=2))
    else:
        for direction in directions:
            for target in data[direction]:
                print(f"{direction}\t{target}")
    return EXIT_OK


def cmd_config_hash(args: argparse.Namespace) -> int:
    from labbrain.confighash import config_hash, load_run_config
    from labbrain.vault import DEFAULT_HASH_IGNORE, VaultNotFound, find_root, load_config

    try:
        ignore = load_config(find_root(explicit=args.vault)).hash_ignore
    except VaultNotFound:
        ignore = DEFAULT_HASH_IGNORE
    try:
        data = load_run_config(args.file)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    print(config_hash(data, ignore))
    return EXIT_OK


def cmd_schema(args: argparse.Namespace) -> int:
    from labbrain.schema import json_schema

    print(json.dumps(json_schema(args.type), indent=2))
    return EXIT_OK


# --- parser -----------------------------------------------------------------------


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json", "github"), default="text")
    parser.add_argument(
        "--json", dest="format", action="store_const", const="json", help="same as --format json"
    )


def _add_id_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("type", choices=NOTE_TYPES)
    parser.add_argument("--title", default="")
    parser.add_argument("--author", default=None)
    parser.add_argument("--agent", default="", help="handoff IDs: agent name (default: author)")
    parser.add_argument("--first-author", default="", help="literature IDs: first author surname")
    parser.add_argument("--year", type=int, help="literature IDs: publication year")
    parser.add_argument("--name", default="", help="protocol IDs: optional EVAL-v<N>-<name>")
    parser.add_argument("--at", default=None, help="ISO datetime to use instead of now")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labbrain", description="Tools for lab-brain vaults.")
    parser.add_argument("--version", action="version", version=f"labbrain {__version__}")
    parser.add_argument("--vault", type=Path, help="vault root (overrides LABBRAIN_VAULT)")
    # Subcommands accept --vault too, because pre-commit appends hook args after the
    # subcommand. SUPPRESS keeps a subcommand from resetting a top-level --vault.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    vault = add("vault", "vault commands")
    vault_sub = vault.add_subparsers(dest="vault_command", required=True)
    root_cmd = vault_sub.add_parser("root", help="print the vault root", parents=[common])
    root_cmd.set_defaults(func=cmd_vault_root)

    p = add("config", "print the resolved config as JSON")
    p.add_argument("--key", help="dotted key, e.g. tracker.backend")
    p.set_defaults(func=cmd_config)

    p = add("new-id", "print a fresh, collision-free ID")
    _add_id_options(p)
    p.set_defaults(func=cmd_new_id)

    p = add("new", "create a skeleton note and print its path")
    _add_id_options(p)
    p.add_argument("--link", action="append", default=[], help="ID to put in `links` (repeatable)")
    p.set_defaults(func=cmd_new)

    p = add("validate", "check single files (used by the write hook)")
    p.add_argument("paths", nargs="+", type=Path)
    _add_format(p)
    p.set_defaults(func=cmd_validate)

    p = add("sync", "propagate supersession and freeze referenced protocols")
    p.add_argument("--dry-run", action="store_true")
    _add_format(p)
    p.set_defaults(func=cmd_sync)

    p = add("index", "regenerate index.md")
    p.add_argument("--check", action="store_true", help="exit 1 if index.md would change")
    p.set_defaults(func=cmd_index)

    p = add("log", "append a line to today's log")
    p.add_argument("text")
    p.add_argument("--author")
    p.set_defaults(func=cmd_log)

    p = add("lint", "run every lint rule over the vault")
    p.add_argument("--base", default="HEAD", help="git revision frozen-edit compares against")
    p.add_argument("--rule", action="append", default=[], help="run only this rule (repeatable)")
    _add_format(p)
    p.set_defaults(func=cmd_lint)

    p = add("phi-scan", "scan files or directories for PHI")
    p.add_argument("paths", nargs="+", type=Path)
    _add_format(p)
    p.set_defaults(func=cmd_phi_scan)

    p = add("list", "list notes")
    p.add_argument("--type", dest="note_type", choices=NOTE_TYPES)
    p.add_argument("--status")
    p.add_argument("--tag")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = add("links", "inbound and outbound links of a note")
    p.add_argument("id")
    direction = p.add_mutually_exclusive_group()
    direction.add_argument("--in", dest="direction", action="store_const", const="in")
    direction.add_argument("--out", dest="direction", action="store_const", const="out")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_links, direction=None)

    p = add("config-hash", "hash a run config the way experiments record it")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_config_hash)

    p = add("schema", "print the JSON Schema of the frontmatter models")
    p.add_argument("type", nargs="?", choices=NOTE_TYPES)
    p.set_defaults(func=cmd_schema)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from labbrain.vault import ConfigError, VaultNotFound

    try:
        return int(args.func(args))
    except (VaultNotFound, ConfigError, UsageError) as exc:
        print(f"labbrain: {exc}", file=sys.stderr)
        return EXIT_USAGE


def run() -> None:
    sys.exit(main())
```

`labbrain/__main__.py`:

```python
from labbrain.cli import run

run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v && uv run labbrain --help && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; `--help` lists every subcommand.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: everything passes.

- [ ] **Step 6: Commit**

```bash
git add labbrain/cli.py labbrain/__main__.py tests/test_cli.py
git commit -m "feat(cli): labbrain command line with lazy imports and exit codes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: Gate completeness, repository PHI check, performance budgets, pre-commit hooks

**Files:**
- Create: `.pre-commit-hooks.yaml`, `tests/test_meta.py`, `tests/test_perf.py`, `tests/test_precommit.py`
- Modify: `tests/test_gate.py` (append), `.github/workflows/ci.yml`
- Test: the files above

**Interfaces:**
- Consumes: `lint.load_rules`, `MUTATIONS`, `phi.scan`, `ScanSettings`, `Vault`, the CLI entry point.
- Produces: `.pre-commit-hooks.yaml` with hook IDs `labbrain-lint` and `labbrain-phi-scan`; CI runs coverage with `--cov-fail-under=85`.

- [ ] **Step 1: Add the completeness check to `tests/test_gate.py`**

Append:

```python
def test_every_rule_has_a_mutation() -> None:
    assert {m.rule for m in MUTATIONS} == set(lint.load_rules())
    assert len(lint.load_rules()) == 16
```

- [ ] **Step 2: Write `tests/test_meta.py`**

```python
"""The repository itself must contain no identifier-like text outside tests/.

docs/superpowers/ is excluded because its planning documents quote example
patterns on purpose; uv.lock is excluded because it is generated.
"""

from __future__ import annotations

from pathlib import Path

from labbrain.phi import ScanSettings, scan

REPO = Path(__file__).resolve().parents[1]
SKIP_TOP = {"tests", "docs", "uv.lock", "dist", "build", "__pycache__"}


def scan_targets() -> list[Path]:
    targets = [p for p in sorted(REPO.iterdir()) if not p.name.startswith(".") and p.name not in SKIP_TOP]
    targets += [p for p in sorted((REPO / "docs").iterdir()) if p.name != "superpowers"]
    return targets


def test_repository_contains_no_identifier_like_text() -> None:
    findings = scan(scan_targets(), root=REPO, settings=ScanSettings(), allow=frozenset())
    assert findings == [], [f.to_dict() for f in findings]
```

- [ ] **Step 3: Write `tests/test_perf.py`**

```python
"""Budgets from the spec: lint < 3 s on 3,000 notes; validate < 300 ms per file."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, TODAY, commit_all, git, make_vault, write

from labbrain import lint
from labbrain.findings import ERROR
from labbrain.vault import Vault

PROTOCOL = """---
id: EVAL-v1
type: protocol
title: "Bulk protocol"
created: 2026-08-01
updated: 2026-08-01
author: alice
status: frozen
tags: []
links: []
version: 1
comparable_with: []
---
## Definition

AUROC on the test split.

## Changes from previous version

First version.

## Known caveats

None.
"""

DATASET = """---
id: DS-20260801-bulk
type: dataset
title: "Bulk dataset"
created: 2026-08-01
updated: 2026-08-01
author: alice
status: active
tags: []
links: [EVAL-v1]
location: "s3://bulk/"
---
## Source

Synthetic.

## Inclusion and exclusion

All rows.

## Split definition

Fixed split.

## Known issues

None.
"""

EXPERIMENT = """---
id: EXP-20260901-run-{i}
type: experiment
title: "Run {i}"
created: 2026-09-01
updated: 2026-09-01
author: alice
status: done
tags: [bulk]
links: []
protocol: EVAL-v1
dataset: DS-20260801-bulk
config_hash: "sha256:bulk-{i}"
metrics:
  - {{name: auroc, value: 0.8, split: test, run_id: run-{i}, as_of: 2026-09-01}}
---
## Hypothesis

Run {i} tests a bulk hypothesis about scaling.

## Setup

Same as the previous run with one change.

## Results

| metric | value | run |
|---|---|---|
| auroc | 0.80 | run-{i} |

## Interpretation

(human) Nothing surprising.

## Next

Continue the sweep.
"""

CONCEPT = """---
id: topic-{i}
type: concept
title: "Topic {i}"
created: 2026-09-02
updated: 2026-09-02
author: bob
status: active
tags: [bulk]
links: [topic-{next}]
sources: [EXP-20260901-run-{i}]
---
## Summary

Topic {i} summarises run {i}.

## Evidence

See [[EXP-20260901-run-{i}]].

## Open questions

None yet.

## Related

[[topic-{next}]] and [[DS-20260801-bulk]]
"""

IDEA = """---
id: IDEA-20261001-bulk-{i}
type: idea
title: "Idea {i}"
created: 2026-10-01
updated: 2026-10-01
author: bob
status: open
tags: [bulk]
links: []
---
Idea {i}: try a different learning rate schedule.
"""


def build_vault(root: Path, per_type: int = 1000) -> Path:
    make_vault(root, MIN_CONFIG)
    write(root, "protocols/EVAL-v1.md", PROTOCOL)
    write(root, "datasets/DS-20260801-bulk.md", DATASET)
    for i in range(per_type):
        nxt = (i + 1) % per_type
        write(root, f"experiments/EXP-20260901-run-{i}.md", EXPERIMENT.format(i=i))
        write(root, f"concepts/topic-{i}.md", CONCEPT.format(i=i, next=nxt))
        write(root, f"ideas/inbox/IDEA-20261001-bulk-{i}.md", IDEA.format(i=i))
    return root


@pytest.mark.slow
def test_lint_budget_on_3000_notes(tmp_path: Path) -> None:
    root = build_vault(tmp_path / "big")
    git(root, "init", "-q", "-b", "main")
    commit_all(root)
    start = time.perf_counter()
    findings = lint.run(Vault.load(root), today=TODAY)
    elapsed = time.perf_counter() - start
    assert [f.to_dict() for f in findings if f.severity == ERROR] == []
    assert elapsed < 3.0, f"lint took {elapsed:.2f}s on 3,000 notes"


@pytest.mark.slow
def test_validate_budget(vault_dir: Path) -> None:
    path = vault_dir / "experiments" / "EXP-20260901-baseline.md"

    def once() -> float:
        start = time.perf_counter()
        subprocess.run(
            [sys.executable, "-m", "labbrain", "validate", str(path)],
            check=True,
            capture_output=True,
        )
        return time.perf_counter() - start

    best = min(once() for _ in range(3))
    assert best < 0.3, f"validate took {best * 1000:.0f} ms"
```

- [ ] **Step 4: Create `.pre-commit-hooks.yaml` and its test**

`.pre-commit-hooks.yaml`:

```yaml
- id: labbrain-lint
  name: labbrain lint
  description: Lint a lab-brain vault (schema, links, frozen notes, PHI).
  entry: labbrain lint
  language: python
  pass_filenames: false
  always_run: true
- id: labbrain-phi-scan
  name: labbrain phi-scan
  description: Scan staged text files for PHI patterns.
  entry: labbrain phi-scan
  language: python
  types: [text]
```

`tests/test_precommit.py`:

```python
"""pre-commit can install and run both hooks from this repository."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.network
@pytest.mark.skipif(shutil.which("pre-commit") is None, reason="pre-commit is not installed")
@pytest.mark.parametrize("hook", ["labbrain-lint", "labbrain-phi-scan"])
def test_hook_runs_clean_on_the_valid_fixture(vault_dir: Path, hook: str) -> None:
    proc = subprocess.run(
        ["pre-commit", "try-repo", str(REPO), hook, "--all-files"],
        cwd=vault_dir,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] **Step 5: Turn on coverage in CI**

In `.github/workflows/ci.yml`, replace `      - run: uv run pytest` with:

```yaml
      - run: uv run pytest --cov --cov-fail-under=85
```

- [ ] **Step 6: Run the new tests**

Run: `uv run pytest tests/test_gate.py tests/test_meta.py tests/test_perf.py tests/test_precommit.py -v`
Expected: all pass (`test_precommit.py` needs network the first time it builds the hook environment). If a performance budget fails, report the measured time instead of raising the threshold; the usual fixes are profiling `Vault.load` and `phi.scan_text`.

- [ ] **Step 7: Run the whole suite with coverage**

Run: `uv run pytest --cov --cov-fail-under=85 && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, coverage ≥ 85% over `schema`, `ids`, `vault`, `phi` and `lint/`.

- [ ] **Step 8: Commit**

```bash
git add .pre-commit-hooks.yaml .github/workflows/ci.yml tests
git commit -m "test: gate completeness, repo PHI check, performance budgets, pre-commit hooks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 18: ADRs, changelog, README and final verification

**Files:**
- Create: eight files under `docs/decisions/`, `CHANGELOG.md`, `tests/test_adrs.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `check_note`, `parse_note`, `Config`.
- Produces: engine ADRs written as valid lab-brain decision notes (the engine dogfoods its own schema).

- [ ] **Step 1: Write the ADR test**

`tests/test_adrs.py`:

```python
"""Engine ADRs are valid lab-brain decision notes."""

from __future__ import annotations

from pathlib import Path

from labbrain.lint.rules.schema_rules import check_note
from labbrain.notes import parse_note
from labbrain.vault import Config

REPO = Path(__file__).resolve().parents[1]
CONFIG = Config(
    project_name="lab-brain engine",
    project_slug="lab-brain",
    lab_members=["jorgebotas"],
    agents=["claude"],
)


def test_engine_adrs_are_valid_decision_notes() -> None:
    paths = sorted((REPO / "docs" / "decisions").glob("ADR-*.md"))
    assert len(paths) == 8
    for path in paths:
        findings = check_note(parse_note(path, REPO), CONFIG)
        assert findings == [], (path.name, [f.to_dict() for f in findings])
```

Run: `uv run pytest tests/test_adrs.py -v`
Expected: FAIL, `assert 0 == 8`.

- [ ] **Step 2: Write the eight ADRs**

Every ADR uses this frontmatter shape (only `id` and `title` change). Write the files exactly as below.

`docs/decisions/ADR-20261015-engine-module-layout.md`:

```markdown
---
id: ADR-20261015-engine-module-layout
type: decision
title: "Engine module layout"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine]
links: []
---
## For future agents

Records why the labbrain package differs from the tree in the parent spec.
Safe to rely on for module responsibilities; the code is the final word.

## Context

The parent spec sketches a single lint.py and no shared finding type. Fourteen-plus rules in one module, and two separate result types for lint and phi-scan, would be hard to test and review.

## Decision

Lint is a package whose rule modules register themselves and are discovered automatically. One Finding type (findings.py) serves lint, validate and phi-scan. Further modules beyond the parent tree: layout.py (constants and path predicates, standard library only), validate.py (single-file checks for the write hook), scaffold.py (labbrain new), sync.py, query.py (list and links), confighash.py, gitutil.py, and __main__.py.

## Alternatives considered

A single lint.py; separate finding classes per tool.

## Consequences

Adding a rule means adding a function in a rule module; nothing else changes. Covers spec ADR items 1 and 16 (module part).
```

`docs/decisions/ADR-20261015-lint-rule-set.md`:

```markdown
---
id: ADR-20261015-lint-rule-set
type: decision
title: "Lint rule set and rule ownership"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, lint]
links: []
---
## For future agents

Records how the parent spec's lint table was changed and why each condition has one owner.
Check this before adding a rule that overlaps an existing one.

## Context

The parent spec's rule table had three conditions owned by two rules each, which makes the gate "each broken fixture triggers exactly its rule" impossible. It also defined two heuristic rules over free prose.

## Decision

Two rules are added: missing-section (warning) and sync-pending (warning; conflicting supersession is an error). cross-protocol checks claims only, using structured frontmatter: a concept citing experiments under different protocols is normal and is not a comparison. undated-fact applies only to agent-authored concepts and claims, line by line. Ownership: a done experiment without a protocol is protocol-missing only; non-comparable evidence is cross-protocol only, while claim-stale covers superseded or failed evidence; an empty concept source list is concept-unsourced only, while the schema rule requires the key to exist.

## Alternatives considered

Prose scanning for cross-protocol and undated-fact; keeping the overlapping conditions.

## Consequences

Sixteen rules, each with a fixture mutation. Covers spec ADR items 2, 3, 4, 6 and 15.
```

`docs/decisions/ADR-20261015-frozen-edit-semantics.md`:

```markdown
---
id: ADR-20261015-frozen-edit-semantics
type: decision
title: "frozen-edit semantics"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, lint]
links: []
---
## For future agents

Defines exactly what may change in a frozen note; the per-type table is in frozen_rules.py.
Check POLICIES there before changing which statuses freeze a note.

## Context

"Append-only" in the parent spec left open which diffs are allowed, and naive status handling let a note be unfrozen in one commit and rewritten in the next.

## Decision

A note is frozen according to its status at the base revision (protocols also when a done experiment references them). Only listed fields may change, and status may change only along a per-type transition table. The body may only gain lines (difflib opcodes equal and insert). Deleting a frozen note is an error; base versions are found by ID so moves are followed. raw/ files must stay byte-identical. The rule reads only files git reports as changed, through one batched cat-file process, and supports --base so CI can compare against the merge base. Without git, or with an unknown base, it emits one info finding and skips.

## Alternatives considered

Frontmatter-only checks, which let Results tables be rewritten; a total freeze, which blocks legitimate appended sections.

## Consequences

Typo fixes in frozen notes require supersession. Covers spec ADR item 5.
```

`docs/decisions/ADR-20261015-phi-scan-design.md`:

```markdown
---
id: ADR-20261015-phi-scan-design
type: decision
title: "PHI scanner design"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, phi]
links: []
---
## For future agents

Explains why PHI findings never contain text and how the allowlist is keyed.
Never add line text or matched values to scanner output.

## Context

The write hook feeds tool output back into model context, so any echoed text is a leak. Line-number allowlists break on every edit above the line, and hashing a short identifier on its own can be reversed by brute force.

## Decision

Findings report path, line, column, rule and span length only. Allowlist entries are keyed by file, rule and a SHA-256 of the whole stripped line. Validation errors are a second leak path, so pydantic errors are rendered without input values, YAML errors are reduced to a line number, and every message passes a sanitizer. Identifier patterns require nearby context words. A small inline count followed by a non-person unit word (seeds, folds and similar) is not flagged; samples is deliberately not exempt. phi-scan skips every dot-directory.

## Alternatives considered

The parent spec's file, line and rule allowlist key; redacted line excerpts in output.

## Consequences

Reviewing a finding means opening the file. Covers spec ADR items 7 and 17.
```

`docs/decisions/ADR-20261015-cli-and-dependencies.md`:

```markdown
---
id: ADR-20261015-cli-and-dependencies
type: decision
title: "CLI framework, YAML handling and Python floor"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, cli]
links: []
---
## For future agents

Explains the dependency choices; check here before adding a runtime dependency.
Startup time matters because hooks call the CLI on every tool use.

## Context

Hooks will run labbrain validate on every write, lint must handle thousands of notes in under three seconds, and several lab members edit the same vault.

## Decision

argparse instead of typer, with heavy imports inside each command. Python 3.11 or newer. PyYAML's libyaml-backed safe loader for reads (ruamel's loader is pure Python since 0.19 and measured 6 s for 3,000 notes against 0.5 s for libyaml), and ruamel.yaml round-trip mode with Obsidian's indentation for writes, so a one-field edit is a one-line diff. Runtime dependencies are pydantic, PyYAML and ruamel.yaml. A global --vault option, also accepted after each subcommand, supports vaults in a subfolder of a code repo under pre-commit. Utility commands list, links, config-hash and schema, plus --format github and a .pre-commit-hooks.yaml, are part of the core.

## Alternatives considered

typer; ruamel for reads as well (too slow without its optional C extension); PyYAML for writes (destroys comments); surgical line patches.

## Consequences

Comment-preserving writes and fast reads use two loaders that must agree on values. Covers spec ADR items 8, 11, 12 and 16.
```

`docs/decisions/ADR-20261015-sync-and-new-commands.md`:

```markdown
---
id: ADR-20261015-sync-and-new-commands
type: decision
title: "labbrain sync and labbrain new"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, cli]
links: []
---
## For future agents

sync owns all derived state transitions; new owns ID minting and skeletons.
Skills should call these instead of editing frontmatter by hand.

## Context

The parent spec says "the tool" marks superseded notes and freezes protocols but assigns that to no command. It also relies on skills writing frontmatter by hand.

## Decision

labbrain sync is idempotent: it sets status and superseded_by on every note another note supersedes, and freezes draft protocols referenced by done experiments, using only transitions frozen-edit allows. Conflicting supersession is reported, never written. labbrain new mints an ID and writes a skeleton generated from the schema registries; every skeleton validates with zero findings.

## Alternatives considered

Leaving propagation to skills; new-id only.

## Consequences

sync-pending warns when sync was not run. Covers spec ADR items 9 and 10.
```

`docs/decisions/ADR-20261015-schema-details.md`:

```markdown
---
id: ADR-20261015-schema-details
type: decision
title: "Schema details not fixed by the parent spec"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, schema]
links: []
---
## For future agents

Lists the schema choices made during implementation that the parent spec left open.
Check here before changing a status enum or how links resolve.

## Context

The parent spec gives no status values for literature and handoff notes, and does not say how notes are keyed or how links to files resolve.

## Decision

Literature status is active or stale; handoff status is final. Protocol version numbers are the only counter in the system. Notes are keyed by filename stem, so an id that disagrees with its filename fires only the schema rule. Wikilinks and embeds whose target contains a slash or a file extension resolve against the filesystem, not the ID map. Links are harvested even when a note fails model validation. Conditional requirements: dataset when an experiment is done, superseded_by when superseded, consolidated_into when an idea is consolidated, and the concept sources key.

## Alternatives considered

Keying notes by the id field; treating every wikilink as an ID.

## Consequences

Renaming a file changes a note's ID. Covers spec ADR items 14 and 18.
```

`docs/decisions/ADR-20261015-mutation-fixtures.md`:

```markdown
---
id: ADR-20261015-mutation-fixtures
type: decision
title: "Mutation-based broken fixtures"
created: 2026-10-15
updated: 2026-10-15
author: claude
status: accepted
tags: [engine, testing]
links: []
---
## For future agents

Broken fixtures are functions in tests/fixtures/mutations.py, not directories.
Each mutation's docstring explains why only its rule fires.

## Context

One static broken vault per rule would mean many near-identical directories that drift from the valid fixture.

## Decision

The valid fixture is static; every broken variant is a named mutation applied to a git copy of it. The harness deletes index.md unless the mutation targets index-stale, and commits every mutation except frozen-edit ones, so frozen-edit sees a diff only when it should. Every linkable fixture note has at least two inbound links, so removing one never creates an orphan.

## Alternatives considered

Static broken directories per rule.

## Consequences

The gate test asserts that the set of rules fired equals exactly the declared rule, and that every rule has a mutation. Covers spec ADR item 13.
```

- [ ] **Step 3: Write `CHANGELOG.md` and update `README.md`**

`CHANGELOG.md`:

```markdown
# Changelog

All notable changes to this project are documented here. Versions follow semantic versioning.

## 0.1.0 (unreleased)

### Added

- `labbrain` Python package and CLI: vault discovery, configuration, frontmatter schemas for
  nine note types, collision-safe IDs, `new`, `validate`, `sync`, `index`, `log`, `list`,
  `links`, `config-hash`, `schema`.
- `labbrain lint` with sixteen rules, JSON and GitHub-annotation output, and `--base` for CI.
- `labbrain phi-scan` with context-aware patterns, small-cell checks and a line-hash allowlist.
- `.pre-commit-hooks.yaml` exposing `labbrain-lint` and `labbrain-phi-scan`.
- Engine ADRs in `docs/decisions/`.
```

Replace the body of `README.md` below the first paragraph with:

```markdown
## Commands

    labbrain vault root                 # where am I?
    labbrain new experiment --title "Label smoothing" --author alice
    labbrain validate experiments/EXP-20261015-label-smoothing.md
    labbrain sync                       # propagate supersession, freeze referenced protocols
    labbrain index                      # regenerate index.md
    labbrain lint                       # all rules; --json or --format github for CI
    labbrain phi-scan .                 # PHI patterns and small cells
    labbrain list --type experiment --status running

Exit codes: 0 clean, 1 errors found, 2 usage or configuration problem.

## Development

    uv sync
    uv run pytest
    uv run pytest --cov --cov-fail-under=85

## Safety

The PHI guardrails make the safe path the default. They do not replace your institution's
DUA, IRB or security rules.
```

- [ ] **Step 4: Run the ADR test**

Run: `uv run pytest tests/test_adrs.py tests/test_meta.py -v`
Expected: PASS. If `test_meta.py` flags an ADR or the README, reword that line rather than allowlisting it.

- [ ] **Step 5: Final verification**

Run each and confirm the expected result:

```bash
uv run pytest --cov --cov-fail-under=85
```

Expected: all tests pass, coverage at least 85%.

```bash
uv run ruff check . && uv run ruff format --check .
```

Expected: no findings.

```bash
uv build
```

Expected: `dist/labbrain-0.1.0.tar.gz` and `dist/labbrain-0.1.0-py3-none-any.whl` are built.

```bash
uv run labbrain --vault tests/fixtures/valid lint
```

Expected: `0 error(s), 0 warning(s), 0 info` and exit code 0. (The fixture sits inside the engine repo, so `frozen-edit` diffs it against the engine's HEAD through the subfolder prefix; with the fixture committed there is no diff.)

- [ ] **Step 6: Commit**

```bash
git add docs/decisions CHANGELOG.md README.md tests/test_adrs.py
git commit -m "docs: engine ADRs, changelog and README for labbrain 0.1.0" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage

| Spec section | Task(s) |
|---|---|
| 1 Scope and gates | 7 (gate test), 17 (completeness), 18 (final verification) |
| 2 Repository layout and module boundaries | 1–16; ADR in 18 |
| 3 Discovery, config, notes, graph, reading and writing | 4, 5 |
| 4 Schemas, authorship | 3, 7 |
| 5 IDs | 2 |
| 6 CLI (all commands, exit codes, JSON, `validate` scope, `new`, `sync`, `index`, `log`, `--vault`, `LABBRAIN_NOW`) | 5, 7, 10, 11, 14, 15, 16 |
| 7 Lint rules, comparability, frozen-edit, undated-fact, sync-pending | 7–14 |
| 8 PHI rules, scope, output, allowlist, sanitization | 1, 3, 4, 5, 14 |
| 9 Testing (fixtures, harness, gate, PHI, performance, coverage, CI) | 6, 7, 14, 17 |
| 10 ADRs | 18 |
| 11 Notes for later sub-projects | Not implemented here by design |
