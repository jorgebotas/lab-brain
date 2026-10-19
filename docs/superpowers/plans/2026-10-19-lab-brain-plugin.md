# lab-brain Plugin and Capture Skills (M4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship engine v0.2.0, which is both the `labbrain` package with the commands the capture skills need and a Claude Code plugin with six skills, served from a single-plugin marketplace in this repo.

**Architecture:**

- Deterministic work lives in new engine modules, each behind a CLI subcommand that keeps v0.1.0's conventions:
  - `trackers/` for the local adapter;
  - `experiments.py` for config diffs and `exp record`;
  - `finish.py`, `codeinfo.py` and `brief.py`.
- Skills are markdown in `skills/<name>/SKILL.md`. They call the engine as `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain …` and never compute anything themselves.
- A manifest test keeps the skills, the manifests and the CLI consistent.
- Opt-in headless smoke tests and a gate script exercise the installed plugin.

**Tech Stack:** Python ≥ 3.11, pydantic 2, PyYAML, ruamel.yaml, pytest, ruff, uv/uvx, hatchling, Claude Code plugins (`.claude-plugin/`), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-19-lab-brain-plugin-design.md` (the source of truth; section numbers below refer to it).

## Global Constraints

**Engine code**

- Python `>=3.11`. Add no runtime dependencies: only `pydantic`, `pyyaml` and `ruamel.yaml`.
- CLI modules import only the standard library and `labbrain.layout` at module level. Every command imports what it needs inside its function, because hooks call this CLI on every tool use.
- **Exit codes:**
  - 0: success;
  - 1: findings only (validate, finish or lint errors);
  - 2: every other failure.
- **Errors:**
  - New engine errors subclass `labbrain.errors.EngineError`. `main()` prints them as `labbrain: <message>` on stderr and returns 2.
  - Messages never contain file contents, config values or frontmatter values. Note IDs pass through `findings.display_id`; run IDs pass through `findings.sanitize`; statuses pass through a fixed label set.
  - Unexpected exceptions keep `main()`'s type-only report.
- Engine commands that create or locate notes print absolute paths.

**Plugin and skills**

- The engine command written in skills (ENGINE) is exactly: `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain`.
- **Permission rules:** every skill's `allowed-tools` lists both:
  - `Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)`
  - `Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)`
- **Shell rules for skill bodies:**
  - never `$(`, and never shell-variable assignment;
  - user-derived text only in single quotes, with `'` written as `'\''`;
  - every `labbrain ` occurrence preceded by `uvx --from "${CLAUDE_PLUGIN_ROOT}" `.
- Plugin name `lab-brain`, marketplace name `lab-brain`, plugin version `0.2.0`. The version lives only in `.claude-plugin/plugin.json` and equals `pyproject.toml` and `labbrain.__version__`.

**Tests and repo hygiene**

- **Test data:**
  - Synthetic identifiers only.
  - No real-looking identifiers anywhere outside `tests/` and `docs/superpowers/`; `tests/test_meta.py` PHI-scans every other tracked file, including `skills/`, `.claude-plugin/` and `scripts/`.
  - The `vault_dir` fixture pins `LABBRAIN_NOW=2026-10-15T12:00:00`, so "today" in tests is `2026-10-15`.
- **Before every commit:** `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` all pass. Line length is 100.
- **Commits:** conventional messages, each ending with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **uv cache.** Verified 2026-10-19 with uv 0.7.17: `[tool.uv] cache-keys = [{ file = "pyproject.toml" }, { file = "labbrain/**/*.py" }]` makes `uvx --from <checkout>` rebuild after source edits; without it, uvx serves a stale build.

## Execution order and parallel waves

Task numbers follow dependency order. Tasks in the same wave touch disjoint modules and can run in parallel worktrees. `labbrain/cli.py` and `tests/helpers.py` are the only shared files. Each task adds its command functions directly above the `# --- parser ---` comment and its parser blocks directly above `return parser`. A merge then has only adjacent-insertion conflicts: keep both sides, in task-number order.

| Wave | Tasks | Needs |
| --- | --- | --- |
| 1 | Task 1 (`new` flags, `EngineError`, exclusive create) | — |
| 2 | Task 2 (`finish`), Task 3 (trackers, `tracker fetch`), Task 5 (`brief`) | Task 1 |
| 3 | Task 4 (`code sha`), Task 6 (`tracker diff`) | Task 3 |
| 4 | Task 7 (`exp record`) | Tasks 2, 4, 6 |
| 5 | Task 8 (manifests, version 0.2.0, six skills) | Task 7 |
| 6 | Task 9 (smoke tests, gate, CI), Task 10 (ADRs, README, CHANGELOG) | Task 8 |

## File map

| File | Task | Responsibility |
| --- | --- | --- |
| `labbrain/errors.py` | 1 | `EngineError`, the base for every printable engine error |
| `labbrain/notes.py` | 1 | `atomic_create`: exclusive, atomic file creation |
| `labbrain/scaffold.py` | 1, 7 | `new` flags, status allowlist, exclusive create with retry, `extra`/`section_text` |
| `labbrain/finish.py` | 2 | validate → sync → index → log |
| `labbrain/sync.py` | 2 | `report()`: sync results as findings, shared by `sync` and `finish` |
| `labbrain/vault.py` | 3 | `Config.dataset_key`, `resolve_config_path()` |
| `labbrain/trackers/{__init__,base,local}.py` | 3 | adapter protocol, `get_adapter`, `describe`, local adapter |
| `labbrain/codeinfo.py` | 4 | `code_sha()` |
| `labbrain/brief.py` | 5 | `build_brief()` |
| `labbrain/confighash.py` | 6 | `is_ignored()` |
| `labbrain/experiments.py` | 6, 7 | `ConfigDiff`, `config_diff`, rendering, `record()` |
| `labbrain/cli.py` | 1–7 | subcommands `new` flags, `finish`, `tracker fetch/diff`, `code sha`, `brief`, `exp record` |
| `.claude-plugin/{plugin,marketplace}.json` | 8 | plugin and marketplace manifests |
| `skills/*/SKILL.md` | 8 | the six skills |
| `tests/smoke/*`, `scripts/m4-gate.sh`, `.github/workflows/*` | 9 | smoke harness, gate, CI |
| `docs/decisions/ADR-*.md`, `README.md`, `CHANGELOG.md` | 10 | four ADRs, docs |

---

### Task 1: `new` flags, `EngineError` and exclusive note creation

**Files:**
- Create: `labbrain/errors.py`
- Modify: `labbrain/notes.py` (add `atomic_create` after `atomic_write`)
- Modify: `labbrain/scaffold.py` (`skeleton`, `create`, new constants)
- Modify: `labbrain/cli.py` (`cmd_new`, the `new` parser, `main`)
- Test: `tests/test_new_flags.py`

**Interfaces:**
- Produces:
  - `labbrain.errors.EngineError(Exception)`.
  - `labbrain.notes.atomic_create(path: Path, text: str) -> None`. Raises `FileExistsError` if `path` exists.
  - `labbrain.scaffold.ScaffoldError(EngineError)`.
  - `scaffold.NEW_STATUSES: dict[str, tuple[str, ...]]`.
  - `scaffold.allowed_statuses(note_type: str) -> tuple[str, ...]`.
  - `scaffold.one_line(text: str) -> str`.
  - `scaffold.CREATE_ATTEMPTS = 5`.
  - `skeleton(..., summary: str = "", body: str = "", tags: Iterable[str] = (), status: str | None = None)`.
  - `create(..., summary: str = "", body: str = "", tags: Iterable[str] = (), status: str | None = None) -> Path`.
  - CLI `new` flags: `--summary`, `--body`, `--tag` (repeatable), `--status`.
  - `main()` catches `EngineError` and returns 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_new_flags.py`:

```python
"""`labbrain new` flags for skills, and exclusive note creation."""

from __future__ import annotations

from pathlib import Path

import pytest

from labbrain import scaffold
from labbrain.cli import main
from labbrain.notes import atomic_create


@pytest.fixture(autouse=True)
def _no_author_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_AUTHOR", raising=False)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def new(capsys: pytest.CaptureFixture[str], *argv: str) -> Path:
    code, out, err = run(capsys, "new", *argv)
    assert code == 0, err
    return Path(out.strip())


def test_summary_replaces_the_placeholder_on_one_line(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = new(
        capsys, "idea", "--title", "Cosine warmup", "--author", "claude",
        "--summary", "Try warmup.\nOn the small model.",
    )
    text = path.read_text(encoding="utf-8")
    assert "## For future agents\n\nTry warmup. On the small model.\n" in text
    assert scaffold.FUTURE_AGENTS_PLACEHOLDER not in text
    assert run(capsys, "validate", str(path))[0] == 0


def test_summary_is_ignored_for_human_authors(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run(
        capsys, "new", "idea", "--title", "Cosine warmup", "--author", "alice",
        "--summary", "Try warmup.",
    )
    assert code == 0 and "--summary is ignored for human authors" in err
    assert "Try warmup." not in Path(out.strip()).read_text(encoding="utf-8")


def test_body_goes_after_the_future_agents_block(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = new(
        capsys, "idea", "--title", "Cosine warmup", "--author", "claude",
        "--summary", "Warmup idea.", "--body", "Don't forget cosine warmup.",
    )
    text = path.read_text(encoding="utf-8")
    assert text.index("## For future agents") < text.index("Don't forget cosine warmup.\n")
    assert run(capsys, "validate", str(path))[0] == 0


def test_body_goes_before_required_sections(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = new(
        capsys, "decision", "--title", "Pick a tracker", "--author", "alice",
        "--body", "Background note.",
    )
    text = path.read_text(encoding="utf-8")
    assert text.index("Background note.") < text.index("## Context")
    assert run(capsys, "validate", str(path))[0] == 0


def test_body_rejects_level_two_headings(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = run(
        capsys, "new", "idea", "--title", "Sneaky", "--author", "claude",
        "--body", "text\n## Sneaky heading",
    )
    assert code == 2 and "level-2 headings" in err
    assert not list((vault_dir / "ideas" / "inbox").glob("IDEA-20261015-*"))


def test_tags_are_deduplicated_in_order(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = new(
        capsys, "idea", "--title", "Cosine warmup", "--author", "alice",
        "--tag", "warmup", "--tag", "optim", "--tag", "warmup", "--tag", " ",
    )
    assert "tags: [warmup, optim]\n" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("note_type", "status"),
    [("experiment", "running"), ("experiment", "planned"), ("decision", "accepted"),
     ("decision", "proposed"), ("idea", "open")],
)
def test_allowed_statuses_produce_valid_notes(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], note_type: str, status: str
) -> None:
    path = new(capsys, note_type, "--title", "Status check", "--author", "alice", "--status", status)
    assert f"status: {status}\n" in path.read_text(encoding="utf-8")
    assert run(capsys, "validate", str(path))[0] == 0


@pytest.mark.parametrize(
    ("note_type", "status"),
    [("experiment", "done"), ("idea", "consolidated"), ("decision", "superseded"),
     ("protocol", "frozen"), ("experiment", "bogus48151623")],
)
def test_other_statuses_are_refused_without_echo(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], note_type: str, status: str
) -> None:
    code, _, err = run(
        capsys, "new", note_type, "--title", "Status check", "--author", "alice", "--status", status
    )
    assert code == 2 and "--status" in err
    assert "48151623" not in err


def test_atomic_create_never_replaces_a_file(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        atomic_create(target, "new text")
    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["note.md"]


def test_atomic_create_writes_a_new_file(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "note.md"
    atomic_create(target, "line\r\n")
    assert target.read_bytes() == b"line\r\n"


def test_create_retries_when_another_writer_wins(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = scaffold.atomic_create
    calls: list[Path] = []

    def racing(path: Path, text: str) -> None:
        calls.append(path)
        if len(calls) == 1:
            path.write_text("someone else's note\n", encoding="utf-8")
            raise FileExistsError(path)
        real(path, text)

    monkeypatch.setattr(scaffold, "atomic_create", racing)
    path = new(capsys, "handoff", "--title", "Wrap up", "--author", "claude")
    first, second = calls
    assert first.read_text(encoding="utf-8") == "someone else's note\n"
    assert path == second and second != first


def test_create_gives_up_after_five_attempts(
    vault_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[Path] = []

    def always_taken(path: Path, text: str) -> None:
        attempts.append(path)
        raise FileExistsError(path)

    monkeypatch.setattr(scaffold, "atomic_create", always_taken)
    code, _, err = run(capsys, "new", "idea", "--title", "Crowded", "--author", "alice")
    assert code == 2 and "could not create" in err
    assert len(attempts) == scaffold.CREATE_ATTEMPTS
```

Run `uv run ruff format tests/test_new_flags.py` after creating it; the argument lists above are compact for the plan.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_new_flags.py -v`
Expected: FAIL. Collection fails with `ImportError: cannot import name 'atomic_create'`.

- [ ] **Step 3: Add `labbrain/errors.py`**

```python
"""Errors whose messages are safe to print; the CLI reports them with exit code 2."""

from __future__ import annotations


class EngineError(Exception):
    """A refused or failed engine operation.

    The message names files, note IDs, run IDs and field names only, never file
    contents, config values or frontmatter values.
    """
```

- [ ] **Step 4: Add `atomic_create` to `labbrain/notes.py`, directly after `atomic_write`**

```python
def atomic_create(path: Path, text: str) -> None:
    """Like atomic_write, but never replace a file: raise FileExistsError instead.

    The text is written to a temp file and hard-linked into place, so the note appears
    complete or not at all, and two writers racing for one ID cannot overwrite each other.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.chmod(tmp, _target_mode(path))
        os.link(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
```

- [ ] **Step 5: Update `labbrain/scaffold.py`**

Change the imports at the top:

```python
from labbrain.errors import EngineError
from labbrain.findings import strip_controls
from labbrain.ids import IdError, new_id, protocol_version
from labbrain.layout import TYPE_FOLDERS
from labbrain.notes import atomic_create, render_note
```

Add after `FUTURE_AGENTS_PLACEHOLDER`:

```python
# Statuses `new --status` accepts beyond each type's default: only those whose skeleton
# validates (a done experiment needs a dataset, a superseded note a successor, ...).
NEW_STATUSES: dict[str, tuple[str, ...]] = {
    "experiment": ("planned", "running"),
    "decision": ("proposed", "accepted"),
}
CREATE_ATTEMPTS = 5


class ScaffoldError(EngineError):
    """A `new` option cannot be honoured."""


def allowed_statuses(note_type: str) -> tuple[str, ...]:
    return NEW_STATUSES.get(note_type, (DEFAULT_STATUS[note_type],))


def one_line(text: str) -> str:
    """`text` on one line: control characters and line breaks become single spaces."""
    return " ".join(strip_controls(text).split())
```

Replace `skeleton` with:

```python
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
    summary: str = "",
    body: str = "",
    tags: Iterable[str] = (),
    status: str | None = None,
) -> str:
    data = CommentedMap()
    data["id"] = note_id
    data["type"] = note_type
    data["title"] = title
    data["created"] = now.date()
    data["updated"] = now.date()
    data["author"] = author
    data["status"] = status or DEFAULT_STATUS[note_type]
    data["tags"] = _flow(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
    data["links"] = _flow(links)
    for key, default in TYPE_FIELDS[note_type].items():
        data[key] = _flow(default) if isinstance(default, list) else default
    for key, value in (extra or {}).items():
        data[key] = value
    sections = []
    if config.is_agent(author):
        line = one_line(summary) or FUTURE_AGENTS_PLACEHOLDER
        sections.append(f"## {FUTURE_AGENTS_HEADING}\n\n{line}\n")
    if body.strip():
        sections.append(body.strip("\n") + "\n")
    sections += [f"## {section}\n" for section in REQUIRED_SECTIONS[note_type]]
    return render_note(data, "\n".join(sections))
```

Replace `create` with:

```python
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
    summary: str = "",
    body: str = "",
    tags: Iterable[str] = (),
    status: str | None = None,
) -> Path:
    if status is not None and status not in allowed_statuses(note_type):
        choices = ", ".join(allowed_statuses(note_type))
        raise ScaffoldError(f"--status for a new {note_type} must be one of: {choices}")
    if any(line.startswith("## ") for line in body.splitlines()):
        raise ScaffoldError("--body must not contain level-2 headings")
    agent = agent or author
    links, tags = list(links), list(tags)
    for _ in range(CREATE_ATTEMPTS):
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
            summary=summary,
            body=body,
            tags=tags,
            status=status,
        )
        try:
            atomic_create(path, text)
        except FileExistsError:
            continue  # another writer took this ID; new_id sees the file next time
        return path
    raise IdError(f"could not create a {note_type} note: every candidate ID was taken")
```

- [ ] **Step 6: Update `labbrain/cli.py`**

Replace `cmd_new` with:

```python
def cmd_new(args: argparse.Namespace) -> int:
    from labbrain.ids import IdError
    from labbrain.scaffold import create

    if not args.title:
        raise UsageError("--title is required")
    author = _author(args)
    root, config = _config(args)
    if args.summary and not config.is_agent(author):
        print("labbrain: note: --summary is ignored for human authors", file=sys.stderr)
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
            summary=args.summary,
            body=args.body,
            tags=args.tag,
            status=args.status,
        )
    except IdError as exc:
        raise UsageError(str(exc)) from exc
    print(path)
    return EXIT_OK
```

In `build_parser`, extend the `new` block:

```python
    p = add("new", "create a skeleton note and print its path")
    _add_id_options(p)
    p.add_argument("--link", action="append", default=[], help="ID to put in `links` (repeatable)")
    p.add_argument("--summary", default="", help="one line for the For-future-agents block")
    p.add_argument("--body", default="", help="text placed before the required sections")
    p.add_argument("--tag", action="append", default=[], help="tag (repeatable)")
    p.add_argument("--status", default=None, help="initial status (default: the type's default)")
    p.set_defaults(func=cmd_new)
```

In `main`, catch `EngineError` alongside the existing errors:

```python
    args = build_parser().parse_args(argv)
    from labbrain.errors import EngineError
    from labbrain.vault import ConfigError, VaultNotFound

    try:
        code = int(args.func(args))
    except (VaultNotFound, ConfigError, UsageError, EngineError) as exc:
        print(f"labbrain: {exc}", file=sys.stderr)
        return EXIT_USAGE
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_new_flags.py tests/test_scaffold.py tests/test_cli.py -v`
Expected: PASS. `test_scaffold.py` still proves that every default skeleton validates.

- [ ] **Step 8: Run the full suite and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add labbrain/errors.py labbrain/notes.py labbrain/scaffold.py labbrain/cli.py tests/test_new_flags.py
git commit -m "feat: add summary, body, tag and status flags to new, with exclusive creation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `labbrain finish` and `new --finish`

**Files:**
- Create: `labbrain/finish.py`
- Modify: `labbrain/sync.py` (add `report`)
- Modify: `labbrain/cli.py` (`cmd_sync` uses `report`; `_finish`, `cmd_finish`, `finish` parser, `--finish` on `new`)
- Test: `tests/test_finish.py`

**Interfaces:**
- Consumes: Task 1's `EngineError`. Existing APIs: `validate.validate_paths(paths, vault=...)`, `sync.plan(vault)`, `sync.apply(vault, changes, today)`, `index.write(vault) -> bool` and `log.append(root, text, when=..., author=...)`.
- Produces:
  - `labbrain.finish.FinishError(EngineError)`.
  - `labbrain.finish.FinishResult(findings: list[Finding], index_updated: bool | None)`.
  - `labbrain.finish.finish(paths: Sequence[Path], *, log_text: str, author: str | None, when: datetime, vault: Path | None = None) -> FinishResult`.
  - `labbrain.sync.report(changes, conflicts, failed, *, verb: str) -> list[Finding]`.
  - CLI helper `_finish(args, paths: list[Path], text: str, author: str | None) -> int`, which Task 7 reuses.
  - CLI `finish PATH... --log TEXT [--author A]`, and `new --finish TEXT`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_finish.py`:

```python
"""`labbrain finish`: validate, then sync, index and log; and `new --finish`."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import note_text, write

from labbrain.cli import main

LOG = Path("log") / "2026-10-15.md"


@pytest.fixture(autouse=True)
def _no_author_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_AUTHOR", raising=False)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_finish_indexes_and_logs_a_clean_note(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out, _ = run(
        capsys, "new", "idea", "--title", "Cosine warmup", "--author", "claude",
        "--summary", "Warmup idea.",
    )
    code, out, _ = run(
        capsys, "finish", out.strip(), "--log", "idea: Cosine warmup", "--author", "claude"
    )
    assert code == 0 and "index.md updated" in out
    assert "[[IDEA-20261015-cosine-warmup]]" in (vault_dir / "index.md").read_text()
    assert "[claude] idea: Cosine warmup" in (vault_dir / LOG).read_text()


def test_finish_stops_on_validation_errors(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = write(
        vault_dir,
        "ideas/inbox/IDEA-20261015-broken.md",
        note_text("IDEA-20261015-broken", "idea", status="bogus"),
    )
    index_before = (vault_dir / "index.md").read_bytes()
    code, out, _ = run(capsys, "finish", str(bad), "--log", "idea: broken")
    assert code == 1 and "error" in out
    assert "index.md" not in out
    assert (vault_dir / "index.md").read_bytes() == index_before
    assert not (vault_dir / LOG).exists()


def test_finish_runs_sync(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    new = write(
        vault_dir,
        "decisions/ADR-20261015-switch-protocol.md",
        note_text(
            "ADR-20261015-switch-protocol",
            "decision",
            status="accepted",
            supersedes="ADR-20260905-adopt-eval-v2",
        ),
    )
    code, out, _ = run(capsys, "finish", str(new), "--log", "decide: switch protocol")
    assert code == 0 and "superseded" in out
    old = (vault_dir / "decisions" / "ADR-20260905-adopt-eval-v2.md").read_text()
    assert "superseded_by: ADR-20261015-switch-protocol" in old
    assert "[[ADR-20261015-switch-protocol]]" in (vault_dir / "index.md").read_text()


def test_new_with_finish_is_one_call(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(
        capsys, "new", "idea", "--title", "Cosine warmup", "--author", "claude",
        "--summary", "Warmup idea.", "--body", "Don't forget it.",
        "--finish", "idea: Cosine warmup",
    )
    assert code == 0
    first = Path(out.splitlines()[0])
    assert first.is_absolute() and first.name == "IDEA-20261015-cosine-warmup.md"
    assert "[[IDEA-20261015-cosine-warmup]]" in (vault_dir / "index.md").read_text()
    assert "[claude] idea: Cosine warmup" in (vault_dir / LOG).read_text()


def test_finish_refuses_paths_outside_the_vault(
    vault_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stray = tmp_path / "elsewhere.md"
    stray.write_text("x\n")
    code, _, err = run(capsys, "finish", str(stray), "--log", "x")
    assert code == 2 and "outside the vault" in err


def test_finish_refuses_empty_log_text(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    note = vault_dir / "ideas" / "inbox" / "IDEA-20261010-smoothing-schedule.md"
    code, _, err = run(capsys, "finish", str(note), "--log", "  ")
    assert code == 2 and "--log" in err


def test_sync_command_output_is_unchanged(
    vault_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "sync", "--dry-run")
    assert code == 0 and out == "0 error(s), 0 warning(s), 0 info\n"
```

Run `uv run ruff format tests/test_finish.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_finish.py -v`
Expected: FAIL. `finish` is not a valid choice (argparse exits 2), and `--finish` is unknown.

- [ ] **Step 3: Add `report` to `labbrain/sync.py`**

Add to the imports: `from labbrain.findings import ERROR, INFO, Finding, sort_findings`. Then append:

```python
def report(
    changes: list[Change], conflicts: list[Conflict], failed: list[Conflict], *, verb: str
) -> list[Finding]:
    """Sync results as findings: conflicts and failed writes are errors, changes are info."""
    findings = [Finding(c.rel, 1, "sync", ERROR, c.message) for c in conflicts + failed]
    failed_rels = {c.rel for c in failed}
    for change in changes:
        if change.rel in failed_rels:
            continue
        fields = ", ".join(f"{key} → {value}" for key, value in change.updates.items())
        findings.append(Finding(change.rel, 1, "sync", INFO, f"{verb}: {fields} ({change.reason})"))
    return sort_findings(findings)
```

- [ ] **Step 4: Create `labbrain/finish.py`**

```python
"""`labbrain finish`: the end step of every writing skill.

Validate the written notes; only when they are clean, propagate supersession,
regenerate index.md and append to today's log. A skill therefore never leaves a
broken note listed in the index or the log.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from labbrain.errors import EngineError
from labbrain.findings import ERROR, Finding, sort_findings


class FinishError(EngineError):
    """finish was called with unusable input."""


@dataclass
class FinishResult:
    findings: list[Finding]
    index_updated: bool | None = None  # None when finish stopped after validation


def finish(
    paths: Sequence[Path],
    *,
    log_text: str,
    author: str | None,
    when: datetime,
    vault: Path | None = None,
) -> FinishResult:
    from labbrain import index, log, sync
    from labbrain.validate import validate_paths
    from labbrain.vault import Vault, find_root

    if not log_text.split():
        raise FinishError("--log text is empty")
    targets = [Path(p).expanduser().resolve() for p in paths]
    root = find_root(start=targets[0].parent, explicit=vault)
    if any(not target.is_relative_to(root) for target in targets):
        raise FinishError("a path is outside the vault")
    findings = validate_paths(targets, vault=root)
    if any(f.severity == ERROR for f in findings):
        return FinishResult(findings)
    loaded = Vault.load(root)
    changes, conflicts = sync.plan(loaded)
    written, failed = sync.apply(loaded, changes, when.date())
    findings = findings + sync.report(changes, conflicts, failed, verb="updated")
    if written:
        loaded = Vault.load(root)
    updated = index.write(loaded)
    log.append(root, log_text, when=when, author=author)
    return FinishResult(sort_findings(findings), updated)
```

- [ ] **Step 5: Update `labbrain/cli.py`**

Replace the body of `cmd_sync` after `verb = …`:

```python
def cmd_sync(args: argparse.Namespace) -> int:
    from labbrain.sync import apply, plan, report
    from labbrain.vault import today

    vault = _vault(args)
    changes, conflicts = plan(vault)
    failed = []
    if not args.dry_run:
        _, failed = apply(vault, changes, today())
    verb = "would update" if args.dry_run else "updated"
    return _emit(report(changes, conflicts, failed, verb=verb), args.format)
```

Add above `# --- parser ---`:

```python
def _finish(args: argparse.Namespace, paths: list[Path], text: str, author: str | None) -> int:
    from labbrain.finish import finish
    from labbrain.vault import now

    result = finish(paths, log_text=text, author=author, when=now(), vault=args.vault)
    code = _emit(result.findings, "text")
    if result.index_updated is not None:
        print("index.md updated" if result.index_updated else "index.md already up to date")
    return code


def cmd_finish(args: argparse.Namespace) -> int:
    return _finish(args, args.paths, args.log, args.author or os.environ.get("LABBRAIN_AUTHOR"))
```

In `cmd_new`, replace the final `print(path)` / `return EXIT_OK` with:

```python
    print(path)
    if args.finish:
        return _finish(args, [path], args.finish, author)
    return EXIT_OK
```

In `build_parser`, add `--finish` to the `new` block, before its `set_defaults`:

```python
    p.add_argument("--finish", default="", help="then run `finish` with this log text")
```

and add above `return parser`:

```python
    p = add("finish", "validate written notes, then sync, regenerate the index and log")
    p.add_argument("paths", nargs="+", type=Path)
    p.add_argument("--log", required=True, help="text for today's log")
    p.add_argument("--author")
    p.set_defaults(func=cmd_finish)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_finish.py tests/test_sync.py tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 7: Full suite and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add labbrain/finish.py labbrain/sync.py labbrain/cli.py tests/test_finish.py
git commit -m "feat: add finish, the validate-sync-index-log end step for skills

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Tracker protocol, local adapter and `tracker fetch`

**Files:**
- Create: `labbrain/trackers/__init__.py`, `labbrain/trackers/base.py`, `labbrain/trackers/local.py`
- Create: `tests/fixtures/runs/<run>/…` (files listed in Step 1)
- Modify: `labbrain/vault.py` (`Config.dataset_key`, `resolve_config_path`)
- Modify: `labbrain/cli.py` (`cmd_tracker_fetch`, the `tracker` parser)
- Modify: `tests/helpers.py` (`RUNS_FIXTURE`, `copy_runs`)
- Modify: `pyproject.toml` (coverage include)
- Test: `tests/test_trackers_local.py`

**Interfaces:**
- Consumes: Task 1's `EngineError`; `confighash.flatten` and `confighash.config_hash`; `findings.sanitize`; `notes.safe_load`.
- Produces:
  - `labbrain.vault.resolve_config_path(base: Path, value: str) -> Path`.
  - `Config.dataset_key: str = "data.dataset"`.
  - From `labbrain.trackers.base`: `RunRecord` (TypedDict), `RUN_STATUSES`, `TrackerError(EngineError)` and `TrackerAdapter` (Protocol: `name`, `fetch(run_ids) -> list[RunRecord]`, `run_url(run_id) -> str | None`).
  - From `labbrain.trackers`: `get_adapter(config, root) -> TrackerAdapter`, `headline(summary, patterns) -> dict[str, float]` and `describe(record, config) -> dict[str, Any]` (JSON-ready, adds `config_hash`, `protocol`, `dataset`, `headline`).
  - From `labbrain.trackers.local`: `LocalAdapter(runs_dir, protected)` with `.from_config(config, root)` and `.runs_dir`, `runs_dir_for(config, root) -> Path` and `protected_roots(config, root) -> list[Path]`.
  - Test helpers: `helpers.RUNS_FIXTURE: Path` and `helpers.copy_runs(vault: Path) -> Path`, which copies the fixture runs to `<vault>/runs`.
  - CLI: `tracker fetch RUN...`.

- [ ] **Step 1: Create the run fixtures**

Create these files exactly. They are synthetic.

`tests/fixtures/runs/run-001/config.yaml`:

```yaml
model:
  name: convnet
  depth: 4
optim:
  lr: 0.001
data:
  dataset: DS-20260801-main-split
  fold: 0
eval:
  protocol: EVAL-v2
seed: 1
```

`tests/fixtures/runs/run-001/metrics.json`:

```json
{"test": {"auroc": 0.81}, "train": {"loss": 0.42}}
```

`tests/fixtures/runs/run-001/meta.json`:

```json
{"name": "baseline", "status": "finished", "git_sha": "1a2b3c4", "git_dirty": false, "tags": ["baseline"]}
```

`tests/fixtures/runs/run-002/config.yaml`:

```yaml
model:
  name: convnet
  depth: 4
optim:
  lr: 0.001
loss:
  label_smoothing: 0.1
data:
  dataset: DS-20260801-main-split
  fold: 0
eval:
  protocol: EVAL-v2
seed: 2
```

`tests/fixtures/runs/run-002/metrics.json`:

```json
{"test": {"auroc": 0.83}}
```

`tests/fixtures/runs/run-002/meta.json`:

```json
{"name": "label-smoothing", "status": "finished", "git_sha": "1a2b3c4", "git_dirty": false}
```

`tests/fixtures/runs/run-c1/config.yaml`:

```yaml
model:
  name: convnet
  depth: 4
  dropout: 0.1
optim:
  lr: 0.0003
loss:
  label_smoothing: 0.1
data:
  dataset: DS-20260801-main-split
  fold: 0
eval:
  protocol: EVAL-v2
seed: 3
```

`tests/fixtures/runs/run-c1/metrics.json`:

```json
{"test": {"auroc": 0.85}, "val": {"auroc": 0.86}, "epoch": 20}
```

`tests/fixtures/runs/run-c1/meta.json`:

```json
{"name": "lr-dropout-fold0", "status": "finished", "started_at": "2026-10-12T09:00:00", "ended_at": "2026-10-12T11:00:00", "tags": ["lr-sweep"], "git_sha": "5D6E7F8", "git_dirty": false, "notes": "Hypothesis: a lower learning rate with dropout beats label smoothing alone on test AUROC."}
```

`tests/fixtures/runs/run-c2/config.yaml`: identical to `run-c1/config.yaml`, except `fold: 1` and `seed: 4`.

`tests/fixtures/runs/run-c2/metrics.json`:

```json
{"test": {"auroc": 0.84}, "val": {"auroc": 0.85}, "epoch": 20}
```

`tests/fixtures/runs/run-c2/meta.json`:

```json
{"name": "lr-dropout-fold1", "status": "finished", "started_at": "2026-10-12T09:05:00", "tags": ["lr-sweep"], "git_sha": "5d6e7f8", "git_dirty": false, "notes": "Hypothesis: a lower learning rate with dropout beats label smoothing alone on test AUROC."}
```

`tests/fixtures/runs/run-failed/config.yaml`: identical to `run-c1/config.yaml`.
`tests/fixtures/runs/run-failed/meta.json`:

```json
{"status": "failed", "git_sha": "5d6e7f8"}
```

`tests/fixtures/runs/run-nometrics/config.yaml`: identical to `run-c1/config.yaml`. There are no other files in it.

`tests/fixtures/runs/run-noproto/config.yaml`: identical to `run-c1/config.yaml`, minus the whole `eval:` block.
`tests/fixtures/runs/run-noproto/metrics.json`:

```json
{"test": {"auroc": 0.8}}
```

Add to `tests/helpers.py`, next to `FIXTURE`:

```python
RUNS_FIXTURE = Path(__file__).parent / "fixtures" / "runs"


def copy_runs(vault: Path) -> Path:
    """Copy the synthetic tracker runs to `<vault>/runs`, the default local runs_dir."""
    return Path(shutil.copytree(RUNS_FIXTURE, vault / "runs"))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_trackers_local.py`:

```python
"""The local tracker adapter, `describe`, and `labbrain tracker fetch`."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, copy_runs, make_vault, write

from labbrain.cli import main
from labbrain.confighash import config_hash
from labbrain.trackers import describe, get_adapter, headline
from labbrain.trackers.base import TrackerError
from labbrain.trackers.local import LocalAdapter
from labbrain.vault import load_config


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = make_vault(tmp_path / "v")
    copy_runs(root)
    return root


def adapter(root: Path) -> LocalAdapter:
    found = get_adapter(load_config(root), root)
    assert isinstance(found, LocalAdapter)
    return found


def add_run(root: Path, run_id: str, files: dict[str, str]) -> None:
    for name, text in files.items():
        write(root, f"runs/{run_id}/{name}", text)


def test_fetch_reads_config_metrics_and_meta(vault: Path) -> None:
    [rec] = adapter(vault).fetch(["run-c1"])
    assert rec["run_id"] == "run-c1" and rec["name"] == "lr-dropout-fold0"
    assert rec["config"]["optim.lr"] == 0.0003
    assert rec["config"]["eval.protocol"] == "EVAL-v2"
    assert rec["summary"] == {"test.auroc": 0.85, "val.auroc": 0.86, "epoch": 20.0}
    assert rec["status"] == "finished"
    assert rec["git_sha"] == "5d6e7f8"
    assert rec["git_dirty"] is False
    assert rec["tags"] == ["lr-sweep"]
    assert rec["started_at"] == datetime(2026, 10, 12, 9, 0)
    assert rec["ended_at"] == datetime(2026, 10, 12, 11, 0)
    assert rec["notes"] is not None and rec["notes"].startswith("Hypothesis:")
    assert rec["url"] is None


def test_fetch_keeps_request_order(vault: Path) -> None:
    assert [r["run_id"] for r in adapter(vault).fetch(["run-c2", "run-c1"])] == ["run-c2", "run-c1"]


def test_metrics_keep_only_finite_numbers(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    add_run(root, "r1", {
        "config.yaml": "a: 1\n",
        "metrics.json": '{"ok": 1, "flag": true, "name": "x", "bad": NaN, "nested": {"f": 0.5}}',
    })
    assert adapter(root).fetch(["r1"])[0]["summary"] == {"ok": 1.0, "nested.f": 0.5}


@pytest.mark.parametrize(
    ("run_id", "status"),
    [("run-failed", "failed"), ("run-nometrics", "unknown"), ("run-noproto", "finished")],
)
def test_status_precedence(vault: Path, run_id: str, status: str) -> None:
    assert adapter(vault).fetch([run_id])[0]["status"] == status


def test_badly_typed_meta_values_are_ignored(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    add_run(root, "r1", {
        "config.yaml": "a: 1\n",
        "metrics.json": '{"m": 1}',
        "meta.json": '{"status": "exploded", "git_sha": "not-a-sha", "tags": "x",'
        ' "git_dirty": "yes", "started_at": "yesterday", "name": 7}',
    })
    rec = adapter(root).fetch(["r1"])[0]
    assert rec["status"] == "finished"
    assert rec["git_sha"] is None and rec["git_dirty"] is None
    assert rec["tags"] == [] and rec["started_at"] is None and rec["name"] is None


@pytest.mark.parametrize("bad", ["../escape", ".hidden", "a/b", "", "run 1", "-flag"])
def test_invalid_run_ids_are_refused_without_echo(vault: Path, bad: str) -> None:
    with pytest.raises(TrackerError) as info:
        adapter(vault).fetch([bad])
    assert str(info.value) == "invalid run id"


def test_missing_run_names_the_file(vault: Path) -> None:
    with pytest.raises(TrackerError, match=r"^run run-missing: config.yaml not found$"):
        adapter(vault).fetch(["run-missing"])


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"config.yaml": "a: [oops48151623\n"}, "config.yaml is not valid YAML"),
        ({"config.yaml": "- 48151623\n"}, "config.yaml is not a mapping"),
        ({"config.yaml": "a: 1\n", "metrics.json": "{48151623"}, "metrics.json is not valid JSON"),
        ({"config.yaml": "a: 1\n", "meta.json": "[48151623]"}, "meta.json is not valid JSON"),
    ],
)
def test_unreadable_files_are_reported_without_content(
    tmp_path: Path, files: dict[str, str], message: str
) -> None:
    root = make_vault(tmp_path / "v")
    add_run(root, "r1", files)
    with pytest.raises(TrackerError) as info:
        adapter(root).fetch(["r1"])
    assert str(info.value) == f"run r1: {message}"
    assert "48151623" not in str(info.value)


def test_runs_dir_resolution(tmp_path: Path) -> None:
    plain = make_vault(tmp_path / "v")
    assert adapter(plain).runs_dir == (plain / "runs").resolve()
    (tmp_path / "code").mkdir()
    beside = make_vault(tmp_path / "w", MIN_CONFIG + "code_repo: ../code\n")
    assert adapter(beside).runs_dir == (tmp_path / "code" / "runs").resolve()
    absolute = make_vault(tmp_path / "x", MIN_CONFIG + f"tracker: {{runs_dir: '{tmp_path / 'abs'}'}}\n")
    assert adapter(absolute).runs_dir == (tmp_path / "abs").resolve()


def test_runs_dir_inside_a_data_path_is_refused(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v", MIN_CONFIG + "data_paths: [runs]\n")
    copy_runs(root)
    with pytest.raises(TrackerError, match="protected data path"):
        adapter(root).fetch(["run-c1"])


def test_one_run_inside_a_data_path_is_refused(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v", MIN_CONFIG + "data_paths: [runs/run-c1]\n")
    copy_runs(root)
    with pytest.raises(TrackerError, match="protected data path"):
        adapter(root).fetch(["run-c1"])
    assert adapter(root).fetch(["run-c2"])[0]["run_id"] == "run-c2"


def test_symlinked_run_into_a_data_path_is_refused(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    root = make_vault(tmp_path / "v", MIN_CONFIG + f"data_paths: ['{secret}']\n")
    copy_runs(root)
    shutil.copytree(root / "runs" / "run-c1", secret / "run-x")
    (root / "runs" / "run-x").symlink_to(secret / "run-x")
    with pytest.raises(TrackerError, match="protected data path"):
        adapter(root).fetch(["run-x"])


def test_run_url(tmp_path: Path) -> None:
    root = make_vault(tmp_path / "v")
    add_run(root, "r1", {"config.yaml": "a: 1\n", "meta.json": '{"url": "https://example.org/r1"}'})
    add_run(root, "r2", {"config.yaml": "a: 1\n"})
    assert adapter(root).run_url("r1") == "https://example.org/r1"
    assert adapter(root).run_url("r2") is None


@pytest.mark.parametrize(
    ("backend", "message"),
    [
        ("wandb", "tracker backend 'wandb' arrives in a later engine version"),
        ("mlflow", "tracker backend 'mlflow' arrives in a later engine version"),
        ("none", "tracker backend 'none' is not supported by exp record yet"),
        ("comet48151623", "unknown tracker backend"),
    ],
)
def test_get_adapter_backends(tmp_path: Path, backend: str, message: str) -> None:
    root = make_vault(tmp_path / "v", MIN_CONFIG + f"tracker: {{backend: {backend}}}\n")
    with pytest.raises(TrackerError) as info:
        get_adapter(load_config(root), root)
    assert str(info.value) == message


def test_describe_adds_derived_keys(vault: Path) -> None:
    config = load_config(vault)
    [rec] = adapter(vault).fetch(["run-c1"])
    out = describe(rec, config)
    assert out["config_hash"] == config_hash(rec["config"], config.hash_ignore)
    assert out["config_hash"].startswith("sha256:")
    assert out["protocol"] == "EVAL-v2"
    assert out["dataset"] == "DS-20260801-main-split"
    assert out["headline"] == rec["summary"]
    assert out["started_at"] == "2026-10-12T09:00:00"
    assert describe(adapter(vault).fetch(["run-noproto"])[0], config)["protocol"] is None


def test_headline_patterns_are_case_sensitive() -> None:
    summary = {"test.auroc": 0.85, "val.auroc": 0.86}
    assert headline(summary, []) == summary
    assert headline(summary, ["test.*"]) == {"test.auroc": 0.85}
    assert headline(summary, ["TEST.*"]) == {}


def test_config_hash_matches_the_config_hash_command(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = load_config(vault)
    expected = describe(adapter(vault).fetch(["run-c1"])[0], config)["config_hash"]
    assert main(["--vault", str(vault), "config-hash", str(vault / "runs/run-c1/config.yaml")]) == 0
    assert capsys.readouterr().out.strip() == expected


def test_tracker_fetch_cli(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--vault", str(vault), "tracker", "fetch", "run-c1", "run-c2"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [d["run_id"] for d in data] == ["run-c1", "run-c2"]
    assert data[0]["protocol"] == "EVAL-v2" and data[0]["headline"]["test.auroc"] == 0.85


def test_tracker_fetch_cli_errors_exit_2(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--vault", str(vault), "tracker", "fetch", "run-missing"]) == 2
    assert capsys.readouterr().err == "labbrain: run run-missing: config.yaml not found\n"
```

Run `uv run ruff format tests/test_trackers_local.py`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_trackers_local.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'labbrain.trackers'`.

- [ ] **Step 4: Update `labbrain/vault.py`**

Add the field to `Config`, after `protocol_key`:

```python
    dataset_key: str = "data.dataset"
```

Add after `find_root_or_none`:

```python
def resolve_config_path(base: Path, value: str) -> Path:
    """A path from config.yaml: `~` expanded, a relative path taken from `base`."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path
```

- [ ] **Step 5: Create `labbrain/trackers/base.py`**

```python
"""The tracker adapter protocol (parent spec section 9).

`search` joins the protocol in M7, with its first real user.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, Protocol, TypedDict

from labbrain.errors import EngineError

RunStatus = Literal["running", "finished", "failed", "unknown"]
RUN_STATUSES: tuple[str, ...] = ("running", "finished", "failed", "unknown")


class RunRecord(TypedDict):
    run_id: str
    name: str | None
    url: str | None
    status: RunStatus
    started_at: datetime | None
    ended_at: datetime | None
    config: dict[str, Any]  # flattened with dot keys
    summary: dict[str, float]
    tags: list[str]
    git_sha: str | None
    git_dirty: bool | None
    notes: str | None


class TrackerError(EngineError):
    """A tracker cannot serve the request."""


class TrackerAdapter(Protocol):
    name: str

    def fetch(self, run_ids: Sequence[str]) -> list[RunRecord]: ...

    def run_url(self, run_id: str) -> str | None: ...
```

- [ ] **Step 6: Create `labbrain/trackers/__init__.py`**

```python
"""Tracker adapters: choose one from the vault config, and describe runs for skills."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from labbrain.confighash import config_hash
from labbrain.trackers.base import RunRecord, TrackerAdapter, TrackerError
from labbrain.vault import Config

LATER_BACKENDS = frozenset({"wandb", "mlflow"})


def get_adapter(config: Config, root: Path) -> TrackerAdapter:
    backend = config.tracker.backend
    if backend == "local":
        from labbrain.trackers.local import LocalAdapter

        return LocalAdapter.from_config(config, root)
    if backend in LATER_BACKENDS:
        raise TrackerError(f"tracker backend '{backend}' arrives in a later engine version")
    if backend == "none":
        raise TrackerError("tracker backend 'none' is not supported by exp record yet")
    raise TrackerError("unknown tracker backend")


def headline(summary: Mapping[str, float], patterns: Iterable[str]) -> dict[str, float]:
    """The summary metrics matching any pattern (case-sensitive), or all when none are set."""
    patterns = list(patterns)
    if not patterns:
        return dict(summary)
    return {k: v for k, v in summary.items() if any(fnmatch.fnmatchcase(k, p) for p in patterns)}


def _config_str(config: Mapping[str, Any], key: str) -> str | None:
    value = config.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def describe(record: RunRecord, config: Config) -> dict[str, Any]:
    """`record` as JSON-ready data, plus config_hash, protocol, dataset and headline."""
    out: dict[str, Any] = dict(record)
    for key in ("started_at", "ended_at"):
        value = record[key]
        out[key] = value.isoformat() if value is not None else None
    out["config_hash"] = config_hash(record["config"], config.hash_ignore)
    out["protocol"] = _config_str(record["config"], config.protocol_key)
    out["dataset"] = _config_str(record["config"], config.dataset_key)
    out["headline"] = headline(record["summary"], config.headline_metrics)
    return out
```

- [ ] **Step 7: Create `labbrain/trackers/local.py`**

```python
"""The `local` tracker: one directory per run under `<runs_dir>/<run_id>/`.

Files: `config.yaml` (required), `metrics.json` and `meta.json` (optional). Every
path is canonicalised and refused when it lies in a protected data path, so a
symlinked run cannot reach individual-level data.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from labbrain.confighash import flatten
from labbrain.findings import sanitize
from labbrain.notes import safe_load
from labbrain.trackers.base import RUN_STATUSES, RunRecord, TrackerError
from labbrain.vault import Config, resolve_config_path

RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SHA_RE = re.compile(r"[0-9a-f]{7,40}")


def runs_dir_for(config: Config, root: Path) -> Path:
    base = resolve_config_path(root, config.code_repo) if config.code_repo.strip() else root
    return resolve_config_path(base, config.tracker.runs_dir).resolve()


def protected_roots(config: Config, root: Path) -> list[Path]:
    return [resolve_config_path(root, p).resolve() for p in config.data_paths if p.strip()]


def _error(run_id: str, problem: str) -> TrackerError:
    return TrackerError(sanitize(f"run {run_id}: {problem}"))


def _read_yaml(path: Path, run_id: str) -> dict[str, Any]:
    try:
        data = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        raise _error(run_id, f"{path.name} is not valid YAML") from None
    if not isinstance(data, dict):
        raise _error(run_id, f"{path.name} is not a mapping")
    return data


def _read_json(path: Path, run_id: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise _error(run_id, f"{path.name} is not valid JSON") from None
    if not isinstance(data, dict):
        raise _error(run_id, f"{path.name} is not valid JSON")
    return data


def _numbers(flat: dict[str, Any]) -> dict[str, float]:
    return {
        key: float(value)
        for key, value in flat.items()
        if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
    }


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _tags(value: Any) -> list[str]:
    return [t for t in value if isinstance(t, str)] if isinstance(value, list) else []


def _sha(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    return lowered if SHA_RE.fullmatch(lowered) else None


class LocalAdapter:
    name = "local"

    def __init__(self, runs_dir: Path, protected: Sequence[Path] = ()) -> None:
        self.runs_dir = runs_dir
        self.protected = list(protected)

    @classmethod
    def from_config(cls, config: Config, root: Path) -> LocalAdapter:
        return cls(runs_dir_for(config, root), protected_roots(config, root))

    def fetch(self, run_ids: Sequence[str]) -> list[RunRecord]:
        return [self._load(run_id) for run_id in run_ids]

    def run_url(self, run_id: str) -> str | None:
        return self._load(run_id)["url"]

    def _guard(self, path: Path) -> Path:
        real = path.resolve()
        for root in self.protected:
            if real == root or root in real.parents:
                raise TrackerError("run path is inside a protected data path")
        return real

    def _load(self, run_id: str) -> RunRecord:
        if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
            raise TrackerError("invalid run id")
        self._guard(self.runs_dir)
        run_dir = self._guard(self.runs_dir / run_id)
        config_path = self._guard(run_dir / "config.yaml")
        if not config_path.is_file():
            raise _error(run_id, "config.yaml not found")
        config = _read_yaml(config_path, run_id)
        metrics_path = self._guard(run_dir / "metrics.json")
        has_metrics = metrics_path.is_file()
        summary = _numbers(flatten(_read_json(metrics_path, run_id))) if has_metrics else {}
        meta_path = self._guard(run_dir / "meta.json")
        meta = _read_json(meta_path, run_id) if meta_path.is_file() else {}
        status = meta.get("status")
        if not isinstance(status, str) or status not in RUN_STATUSES:
            status = "finished" if has_metrics else "unknown"
        dirty = meta.get("git_dirty")
        return RunRecord(
            run_id=run_id,
            name=_text(meta.get("name")),
            url=_text(meta.get("url")),
            status=status,  # type: ignore[typeddict-item]
            started_at=_when(meta.get("started_at")),
            ended_at=_when(meta.get("ended_at")),
            config=flatten(config),
            summary=summary,
            tags=_tags(meta.get("tags")),
            git_sha=_sha(meta.get("git_sha")),
            git_dirty=dirty if isinstance(dirty, bool) else None,
            notes=_text(meta.get("notes")),
        )
```

- [ ] **Step 8: Add `tracker fetch` to `labbrain/cli.py`**

Above `# --- parser ---`:

```python
def cmd_tracker_fetch(args: argparse.Namespace) -> int:
    from labbrain.trackers import describe, get_adapter

    root, config = _config(args)
    records = get_adapter(config, root).fetch(args.runs)
    print(json.dumps([describe(r, config) for r in records], indent=2, default=str))
    return EXIT_OK
```

Above `return parser`:

```python
    tracker = add("tracker", "tracker commands")
    tracker_sub = tracker.add_subparsers(dest="tracker_command", required=True)
    p = tracker_sub.add_parser("fetch", help="print runs as JSON", parents=[common])
    p.add_argument("runs", nargs="+", metavar="RUN")
    p.set_defaults(func=cmd_tracker_fetch)
```

- [ ] **Step 9: Measure coverage of the new package**

In `pyproject.toml`, add `"*/labbrain/trackers/*",` to `[tool.coverage.report] include`.

- [ ] **Step 10: Run the tests to verify they pass**

Run: `uv run pytest tests/test_trackers_local.py tests/test_vault.py -v`
Expected: PASS. If `test_symlinked_run_into_a_data_path_is_refused` cannot create symlinks on the platform, the test must still pass on macOS and Linux CI; do not skip it.

- [ ] **Step 11: Full suite, coverage and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest --cov --cov-fail-under=85`
Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add labbrain/trackers labbrain/vault.py labbrain/cli.py tests/fixtures/runs tests/helpers.py tests/test_trackers_local.py pyproject.toml
git commit -m "feat: add the tracker protocol, the local adapter and tracker fetch

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `labbrain code sha`

**Files:**
- Create: `labbrain/codeinfo.py`
- Modify: `labbrain/cli.py` (`cmd_code_sha`, the `code` parser)
- Test: `tests/test_codeinfo.py`

**Interfaces:**
- Consumes: `gitutil.open_repo(path) -> Repo | None`, `Repo.git(*args) -> bytes`, `Repo.top` and `gitutil.GitError`; Task 1's `EngineError`; Task 3's `vault.resolve_config_path`.
- Produces:
  - `labbrain.codeinfo.CodeError(EngineError)`.
  - `labbrain.codeinfo.CodeInfo(sha: str, dirty: bool)`, a frozen dataclass.
  - `labbrain.codeinfo.code_sha(repo_path: Path, *, exclude: Path | None = None) -> CodeInfo`.
  - CLI `code sha [--repo PATH]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_codeinfo.py`:

```python
"""`code_sha` and `labbrain code sha`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, commit_all, git, make_vault, write

from labbrain.cli import main
from labbrain.codeinfo import CodeError, code_sha


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_VAULT", raising=False)


def code_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    write(path, "train.py", "print('train')\n")
    commit_all(path)
    return path


def test_clean_repo(tmp_path: Path) -> None:
    repo = code_repo(tmp_path / "code")
    info = code_sha(repo)
    assert info.sha == git(repo, "rev-parse", "HEAD").strip() and len(info.sha) == 40
    assert info.dirty is False


def test_tracked_and_untracked_changes_are_dirty(tmp_path: Path) -> None:
    repo = code_repo(tmp_path / "code")
    write(repo, "train.py", "print('changed')\n")
    assert code_sha(repo).dirty is True
    git(repo, "checkout", "--", "train.py")
    write(repo, "new.py", "x = 1\n")
    assert code_sha(repo).dirty is True


def test_changes_inside_the_vault_are_ignored(tmp_path: Path) -> None:
    repo = code_repo(tmp_path / "code")
    vault = make_vault(repo / "brain")
    commit_all(repo)
    write(vault, "ideas/inbox/IDEA-20261015-x.md", "x\n")
    assert code_sha(repo, exclude=vault).dirty is False
    assert code_sha(repo).dirty is True


def test_not_a_repository(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    for path in (tmp_path / "plain", tmp_path / "missing"):
        with pytest.raises(CodeError, match="^not a git repository$"):
            code_sha(path)


def test_repository_without_commits(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    git(repo, "init", "-q")
    with pytest.raises(CodeError, match="no commits"):
        code_sha(repo)


def test_cli_uses_code_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = code_repo(tmp_path / "code")
    vault = make_vault(tmp_path / "v", MIN_CONFIG + "code_repo: ../code\n")
    assert main(["--vault", str(vault), "code", "sha"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"repo": "../code", "sha": code_sha(repo).sha, "dirty": False}


def test_cli_explicit_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = code_repo(tmp_path / "code")
    vault = make_vault(tmp_path / "v")
    assert main(["--vault", str(vault), "code", "sha", "--repo", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["repo"] == str(repo)


def test_cli_without_a_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = make_vault(tmp_path / "v")
    assert main(["--vault", str(vault), "code", "sha"]) == 2
    assert capsys.readouterr().err == "labbrain: code repo not set\n"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_codeinfo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'labbrain.codeinfo'`.

- [ ] **Step 3: Create `labbrain/codeinfo.py`**

```python
"""`labbrain code sha`: the code repository's commit, and whether it has uncommitted work.

When the vault lives inside the code repository, its own directory is left out of
the dirty check, so writing a note never makes the code look modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from labbrain import gitutil
from labbrain.errors import EngineError


class CodeError(EngineError):
    """The code repository cannot be read."""


@dataclass(frozen=True)
class CodeInfo:
    sha: str
    dirty: bool


def code_sha(repo_path: Path, *, exclude: Path | None = None) -> CodeInfo:
    repo = gitutil.open_repo(repo_path) if repo_path.is_dir() else None
    if repo is None:
        raise CodeError("not a git repository")
    try:
        sha = repo.git("rev-parse", "--verify", "HEAD").decode().strip()
    except gitutil.GitError:
        raise CodeError("the code repository has no commits") from None
    pathspec = ["."]
    if exclude is not None:
        excluded = exclude.resolve()
        if excluded != repo.top and excluded.is_relative_to(repo.top):
            pathspec.append(f":(exclude){excluded.relative_to(repo.top).as_posix()}")
    try:
        status = repo.git("status", "--porcelain", "--untracked-files=normal", "--", *pathspec)
    except gitutil.GitError:
        raise CodeError("git status failed in the code repository") from None
    return CodeInfo(sha, bool(status.strip()))
```

- [ ] **Step 4: Add `code sha` to `labbrain/cli.py`**

Above `# --- parser ---`:

```python
def cmd_code_sha(args: argparse.Namespace) -> int:
    from labbrain.codeinfo import code_sha
    from labbrain.vault import resolve_config_path

    root, config = _config(args)
    if args.repo:
        label, path = args.repo, Path(args.repo).expanduser()
    elif config.code_repo.strip():
        label, path = config.code_repo, resolve_config_path(root, config.code_repo)
    else:
        raise UsageError("code repo not set")
    info = code_sha(path, exclude=root)
    print(json.dumps({"repo": label, "sha": info.sha, "dirty": info.dirty}))
    return EXIT_OK
```

Above `return parser`:

```python
    code = add("code", "code repository commands")
    code_sub = code.add_subparsers(dest="code_command", required=True)
    p = code_sub.add_parser("sha", help="print the code repo's commit and dirty flag", parents=[common])
    p.add_argument("--repo", help="code repository (default: code_repo from config)")
    p.set_defaults(func=cmd_code_sha)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_codeinfo.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add labbrain/codeinfo.py labbrain/cli.py tests/test_codeinfo.py
git commit -m "feat: add code sha, excluding the vault from the dirty check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `labbrain brief`

**Files:**
- Create: `labbrain/brief.py`
- Modify: `labbrain/cli.py` (`cmd_brief`, the `brief` parser)
- Test: `tests/test_brief.py`

**Interfaces:**
- Consumes: `Vault.load`, `Vault.of_type(note_type) -> list[Note]`, `Note.stem`, `Note.get_str`, `lint.run(vault) -> list[Finding]`, `vault.version_warning(config) -> str | None`, `findings.strip_controls` and `findings.ERROR`/`WARNING`.
- Produces: `labbrain.brief.build_brief(vault: Vault, findings: list[Finding], *, short: bool, warning: str | None) -> str`; CLI `brief [--short]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_brief.py`:

```python
"""`labbrain brief`: a compact orientation for the start of a session."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from helpers import MIN_CONFIG, make_vault, note_text, write

from labbrain import __version__
from labbrain.cli import main


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_short_brief_on_the_fixture(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "brief", "--short")
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        f"Toy Image Classifier · engine {__version__}",
        "Last handoff: HO-20261014-1420-claude  Registered the headline AUROC claim",
        "Running 0 · Planned 0 · Stale claims 0 · Open ideas 1 · Lint errors 0",
    ]


def test_full_brief_on_the_fixture(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "brief")
    assert code == 0
    assert out.splitlines() == [
        f"Toy Image Classifier · engine {__version__}",
        "",
        "Recent handoffs:",
        "  HO-20261014-1420-claude  Registered the headline AUROC claim",
        "",
        "Experiments running (0):",
        "  none",
        "Experiments planned (0):",
        "  none",
        "Stale claims (0):",
        "  none",
        "",
        "Open ideas: 1 · Lint: 0 errors, 0 warnings",
    ]


@pytest.fixture
def busy_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LABBRAIN_NOW", "2026-10-15T12:00:00")
    root = make_vault(tmp_path / "v", MIN_CONFIG + "engine_min_version: 99.0.0\n")
    for day in range(1, 6):
        hid = f"HO-202610{day:02d}-0900-claude"
        write(root, f"handoffs/{hid}.md", note_text(hid, "handoff", title=f"Session {day}"))
    for i in range(7):
        eid = f"EXP-2026100{i}-run{i}"
        title = "Bad\x1btitle" if i == 6 else f"Running {i}"
        write(root, f"experiments/{eid}.md", note_text(eid, "experiment", status="running", title=title))
    for i in range(2):
        eid = f"EXP-2026090{i}-plan{i}"
        write(root, f"experiments/{eid}.md", note_text(eid, "experiment", title=f"Plan {i}"))
    for i in range(6):
        cid = f"CLM-2026100{i}-claim{i}"
        write(root, f"claims/{cid}.md", note_text(cid, "claim", status="stale"))
    for i in range(3):
        iid = f"IDEA-2026100{i}-idea{i}"
        write(root, f"ideas/inbox/{iid}.md", note_text(iid, "idea"))
    write(root, "ideas/inbox/IDEA-20261009-broken.md", note_text("IDEA-20261009-broken", "idea", status="bogus"))
    return root


def test_full_brief_stays_within_limits(busy_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "--vault", str(busy_vault), "brief")
    lines = out.splitlines()
    assert code == 0 and err == "" and len(lines) <= 40
    assert sum("99.0.0" in line for line in lines) == 1
    assert lines[4:7] == [
        "  HO-20261005-0900-claude  Session 5",
        "  HO-20261004-0900-claude  Session 4",
        "  HO-20261003-0900-claude  Session 3",
    ]
    assert "Experiments running (7):" in lines
    assert "  EXP-20261006-run6  Bad title" in lines
    assert "  … and 2 more" in lines and "  … and 1 more" in lines
    assert "Experiments planned (2):" in lines and "Stale claims (6):" in lines
    assert re.fullmatch(r"Open ideas: 3 · Lint: [1-9]\d* errors, \d+ warnings", lines[-1])


def test_short_brief_stays_within_limits(busy_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--vault", str(busy_vault), "brief", "--short")
    lines = out.splitlines()
    assert code == 0 and len(lines) == 4
    assert lines[2] == "Last handoff: HO-20261005-0900-claude  Session 5"
    assert lines[3].startswith("Running 7 · Planned 2 · Stale claims 6 · Open ideas 3 · Lint errors ")


def test_brief_without_handoffs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_vault(tmp_path / "v")
    code, out, _ = run(capsys, "--vault", str(root), "brief", "--short")
    assert code == 0 and "Last handoff: none" in out.splitlines()
```

Run `uv run ruff format tests/test_brief.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_brief.py -v`
Expected: FAIL. `brief` is not a valid choice.

- [ ] **Step 3: Create `labbrain/brief.py`**

```python
"""`labbrain brief`: recent handoffs, open work and vault health in a few lines.

Prints note IDs and titles (what index.md already holds), never body text.
"""

from __future__ import annotations

from labbrain import __version__
from labbrain.findings import ERROR, WARNING, Finding, strip_controls
from labbrain.notes import Note
from labbrain.vault import Vault

HANDOFF_LIMIT = 3
LIST_LIMIT = 5


def _clean(text: str) -> str:
    return " ".join(strip_controls(text).split())


def _title(note: Note) -> str:
    return _clean(note.get_str("title") or "")


def _newest(notes: list[Note]) -> list[Note]:
    return sorted(notes, key=lambda n: n.stem, reverse=True)


def _with_status(vault: Vault, note_type: str, status: str) -> list[Note]:
    return _newest([n for n in vault.of_type(note_type) if n.get_str("status") == status])


def _listing(notes: list[Note], limit: int) -> list[str]:
    if not notes:
        return ["  none"]
    rows = [f"  {n.stem}  {_title(n)}" for n in notes[:limit]]
    if len(notes) > limit:
        rows.append(f"  … and {len(notes) - limit} more")
    return rows


def build_brief(
    vault: Vault, findings: list[Finding], *, short: bool, warning: str | None
) -> str:
    head = [f"{_clean(vault.config.project_name)} · engine {__version__}"]
    if warning:
        head.append(f"warning: {_clean(warning)}")
    handoffs = _newest(vault.of_type("handoff"))
    running = _with_status(vault, "experiment", "running")
    planned = _with_status(vault, "experiment", "planned")
    stale = _with_status(vault, "claim", "stale")
    open_ideas = len(_with_status(vault, "idea", "open"))
    errors = sum(1 for f in findings if f.severity == ERROR)
    warnings = sum(1 for f in findings if f.severity == WARNING)
    if short:
        last = f"{handoffs[0].stem}  {_title(handoffs[0])}" if handoffs else "none"
        counts = (
            f"Running {len(running)} · Planned {len(planned)} · Stale claims {len(stale)}"
            f" · Open ideas {open_ideas} · Lint errors {errors}"
        )
        return "\n".join([*head, f"Last handoff: {last}", counts]) + "\n"
    lines = [*head, "", "Recent handoffs:"]
    lines += [f"  {n.stem}  {_title(n)}" for n in handoffs[:HANDOFF_LIMIT]] or ["  none"]
    lines.append("")
    for label, notes in (
        ("Experiments running", running),
        ("Experiments planned", planned),
        ("Stale claims", stale),
    ):
        lines += [f"{label} ({len(notes)}):", *_listing(notes, LIST_LIMIT)]
    lines += ["", f"Open ideas: {open_ideas} · Lint: {errors} errors, {warnings} warnings"]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Add `brief` to `labbrain/cli.py`**

Above `# --- parser ---`:

```python
def cmd_brief(args: argparse.Namespace) -> int:
    from labbrain import lint
    from labbrain.brief import build_brief
    from labbrain.vault import Vault, load_config, version_warning

    root = _root(args)
    config = load_config(root)  # no stderr warning: the brief prints it once itself
    vault = Vault.load(root, config)
    text = build_brief(vault, lint.run(vault), short=args.short, warning=version_warning(config))
    print(text, end="")
    return EXIT_OK
```

Above `return parser`:

```python
    p = add("brief", "print where the project stands")
    p.add_argument("--short", action="store_true", help="at most four lines (SessionStart hook)")
    p.set_defaults(func=cmd_brief)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_brief.py -v`
Expected: PASS. If `test_short_brief_on_the_fixture` fails on the lint count, run `uv run labbrain --vault tests/fixtures/valid lint` to see the findings. The valid fixture must stay at zero errors and zero warnings; do not change the expected lines.

- [ ] **Step 6: Full suite and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add labbrain/brief.py labbrain/cli.py tests/test_brief.py
git commit -m "feat: add brief and brief --short

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Config diff and `labbrain tracker diff`

**Files:**
- Create: `labbrain/experiments.py`
- Modify: `labbrain/confighash.py` (`is_ignored`; `config_hash` uses it)
- Modify: `labbrain/cli.py` (`cmd_tracker_diff`, `diff` under the `tracker` parser)
- Modify: `pyproject.toml` (coverage include)
- Test: `tests/test_experiments.py`

**Interfaces:**
- Consumes: Task 3's `get_adapter` and `RunRecord`; Task 1's `EngineError`; `findings.display_id`.
- Produces:
  - `labbrain.confighash.is_ignored(key: str, patterns: Iterable[str]) -> bool`.
  - From `labbrain.experiments`:
    - `RecordError(EngineError)`;
    - `ConfigDiff(parent, added, removed, changed, varied_here, varied_parent)` with `.empty`;
    - `split_common(configs, ignore) -> tuple[dict[str, Any], list[str]]`;
    - `config_diff(parent_id, parent_configs, child_configs, ignore) -> ConfigDiff`;
    - `parent_run_ids(vault, parent_id) -> list[str]`;
    - `render_setup(diff) -> str`;
    - `render_runs(run_ids, varied) -> str`;
    - `escape_cell(text) -> str`.
  - CLI `tracker diff RUN... --parent EXP-ID`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiments.py`:

```python
"""Config diffs between run groups, and `labbrain tracker diff`."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import copy_runs, note_text, write

from labbrain.cli import main
from labbrain.experiments import (
    RecordError,
    config_diff,
    parent_run_ids,
    render_runs,
    render_setup,
    split_common,
)
from labbrain.vault import Vault

PARENT = "EXP-20260910-label-smoothing"
IGNORE = ["seed", "*.seed"]

EXPECTED_SETUP = """\
Config diff against [[EXP-20260910-label-smoothing]] (hash_ignore keys omitted):

| key | parent | this |
| --- | --- | --- |
| model.dropout | — | 0.1 |
| optim.lr | 0.001 | 0.0003 |

Varied across these runs: data.fold.
"""


def test_split_common() -> None:
    configs = [{"a": 1, "b": 2, "seed": 1}, {"a": 1, "b": 3, "seed": 2}]
    assert split_common(configs, IGNORE) == ({"a": 1}, ["b"])
    assert split_common([{"a": 1}, {"a": 1, "c": 5}], []) == ({"a": 1}, ["c"])
    assert split_common([], []) == ({}, [])


def test_added_removed_changed() -> None:
    diff = config_diff(
        PARENT, [{"lr": 0.001, "old": 1, "same": 2}], [{"lr": 0.0003, "new": 0.1, "same": 2}], []
    )
    assert diff.added == {"new": 0.1}
    assert diff.removed == {"old": 1}
    assert diff.changed == {"lr": (0.001, 0.0003)}
    assert not diff.empty


def test_varied_keys_stay_out_of_added_and_removed() -> None:
    parent = [{"k": 1, "p": 1}, {"k": 1, "p": 2}]
    child = [{"k": 1, "f": 0}, {"k": 1, "f": 1}]
    diff = config_diff(PARENT, parent, child, [])
    assert (diff.added, diff.removed, diff.changed) == ({}, {}, {})
    assert diff.varied_here == ["f"] and diff.varied_parent == ["p"]


def test_hash_ignore_keys_are_dropped() -> None:
    diff = config_diff(PARENT, [{"a": 1, "seed": 1}], [{"a": 1, "seed": 2}], IGNORE)
    assert diff.empty and diff.varied_here == []


def test_render_setup_table() -> None:
    diff = config_diff(
        PARENT,
        [{"optim.lr": 0.001, "data.fold": 0}],
        [
            {"optim.lr": 0.0003, "model.dropout": 0.1, "data.fold": 0},
            {"optim.lr": 0.0003, "model.dropout": 0.1, "data.fold": 1},
        ],
        [],
    )
    assert render_setup(diff) == EXPECTED_SETUP


def test_render_escapes_pipes_and_marks_removed_keys() -> None:
    diff = config_diff(PARENT, [{"a|b": "x|y", "gone": True}], [{"a|b": "z"}], [])
    text = render_setup(diff)
    assert '| a\\|b | "x\\|y" | "z" |' in text
    assert "| gone | true | — |" in text


def test_render_without_differences() -> None:
    diff = config_diff(PARENT, [{"a": 1}, {"a": 1, "p": 2}], [{"a": 1}], [])
    assert render_setup(diff) == (
        "Same config as [[EXP-20260910-label-smoothing]] (hash_ignore keys omitted).\n"
        "\n"
        "Varied across the parent's runs: p.\n"
    )


def test_render_runs() -> None:
    assert render_runs(["run-a", "run-b"], ["data.fold"]) == (
        "Runs: run-a, run-b.\nVaried across these runs: data.fold.\n"
    )
    assert render_runs(["run-a"], []) == "Runs: run-a.\n"


def test_parent_run_ids(vault_dir: Path) -> None:
    vault = Vault.load(vault_dir)
    assert parent_run_ids(vault, PARENT) == ["run-002"]
    with pytest.raises(RecordError, match="^no experiment with ID EXP-20990101-nope$"):
        parent_run_ids(vault, "EXP-20990101-nope")
    with pytest.raises(RecordError, match="^no experiment with ID IDEA-20261010-smoothing-schedule$"):
        parent_run_ids(vault, "IDEA-20261010-smoothing-schedule")
    write(vault_dir, "experiments/EXP-20261015-planned.md", note_text("EXP-20261015-planned", "experiment"))
    with pytest.raises(RecordError, match="^parent EXP-20261015-planned has no run ids$"):
        parent_run_ids(Vault.load(vault_dir), "EXP-20261015-planned")


def test_unknown_parent_ids_are_not_echoed(vault_dir: Path) -> None:
    with pytest.raises(RecordError) as info:
        parent_run_ids(Vault.load(vault_dir), "Jane Doe 48151623")
    assert "48151623" not in str(info.value)


def test_tracker_diff_cli(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    copy_runs(vault_dir)
    assert main(["tracker", "diff", "run-c1", "run-c2", "--parent", PARENT]) == 0
    assert capsys.readouterr().out == EXPECTED_SETUP


def test_tracker_diff_cli_unknown_parent(vault_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    copy_runs(vault_dir)
    assert main(["tracker", "diff", "run-c1", "--parent", "EXP-20990101-nope"]) == 2
    assert "no experiment with ID" in capsys.readouterr().err
```

Run `uv run ruff format tests/test_experiments.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiments.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'labbrain.experiments'`.

- [ ] **Step 3: Add `is_ignored` to `labbrain/confighash.py`**

Add above `config_hash`, and use it there:

```python
def is_ignored(key: str, patterns: Iterable[str]) -> bool:
    """True when a flattened config key matches a hash_ignore pattern (case-sensitive)."""
    return any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)


def config_hash(config: Mapping[str, Any], ignore: Iterable[str]) -> str:
    patterns = list(ignore)
    kept = {key: value for key, value in flatten(config).items() if not is_ignored(key, patterns)}
    payload = json.dumps(kept, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Create `labbrain/experiments.py`**

```python
"""Experiment notes from tracker runs: config diffs (`tracker diff`) and `exp record`."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from labbrain.confighash import is_ignored
from labbrain.errors import EngineError
from labbrain.findings import display_id
from labbrain.vault import Vault

_ABSENT = object()


class RecordError(EngineError):
    """`tracker diff` or `exp record` cannot proceed."""


@dataclass(frozen=True)
class ConfigDiff:
    parent: str
    added: dict[str, Any]
    removed: dict[str, Any]
    changed: dict[str, tuple[Any, Any]]
    varied_here: list[str]
    varied_parent: list[str]

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def split_common(
    configs: Sequence[Mapping[str, Any]], ignore: Iterable[str]
) -> tuple[dict[str, Any], list[str]]:
    """(keys equal in every config, keys missing from some or differing), hash_ignore dropped."""
    patterns = list(ignore)
    kept = [{k: v for k, v in c.items() if not is_ignored(k, patterns)} for c in configs]
    common: dict[str, Any] = {}
    varied: list[str] = []
    for key in sorted(set().union(*kept)):
        values = [c[key] for c in kept if key in c]
        if len(values) == len(kept) and all(v == values[0] for v in values[1:]):
            common[key] = values[0]
        else:
            varied.append(key)
    return common, varied


def config_diff(
    parent_id: str,
    parent_configs: Sequence[Mapping[str, Any]],
    child_configs: Sequence[Mapping[str, Any]],
    ignore: Iterable[str],
) -> ConfigDiff:
    patterns = list(ignore)
    parent, varied_parent = split_common(parent_configs, patterns)
    child, varied_here = split_common(child_configs, patterns)
    skip = set(varied_parent) | set(varied_here)
    return ConfigDiff(
        parent=parent_id,
        added={k: child[k] for k in sorted(child) if k not in parent and k not in skip},
        removed={k: parent[k] for k in sorted(parent) if k not in child and k not in skip},
        changed={
            k: (parent[k], child[k])
            for k in sorted(child)
            if k in parent and k not in skip and parent[k] != child[k]
        },
        varied_here=varied_here,
        varied_parent=varied_parent,
    )


def parent_run_ids(vault: Vault, parent_id: str) -> list[str]:
    note = vault.get(parent_id)
    if note is None or note.type != "experiment":
        raise RecordError(f"no experiment with ID {display_id(parent_id, vault.notes)}")
    tracker = note.get("tracker")
    run_ids = tracker.get("run_ids") if isinstance(tracker, dict) else None
    ids = [r for r in run_ids if isinstance(r, str)] if isinstance(run_ids, list) else []
    if not ids:
        raise RecordError(f"parent {parent_id} has no run ids")
    return ids


def escape_cell(text: str) -> str:
    return text.replace("|", "\\|")


def _cell(value: Any) -> str:
    if value is _ABSENT:
        return "—"
    return escape_cell(json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str))


def _varied(keys: Sequence[str], label: str) -> list[str]:
    return [f"{label}: {', '.join(keys)}."] if keys else []


def render_setup(diff: ConfigDiff) -> str:
    link = f"[[{diff.parent}]]"
    if diff.empty:
        lines = [f"Same config as {link} (hash_ignore keys omitted)."]
    else:
        lines = [
            f"Config diff against {link} (hash_ignore keys omitted):",
            "",
            "| key | parent | this |",
            "| --- | --- | --- |",
        ]
        rows: dict[str, tuple[Any, Any]] = {k: (_ABSENT, v) for k, v in diff.added.items()}
        rows.update({k: (v, _ABSENT) for k, v in diff.removed.items()})
        rows.update(diff.changed)
        for key in sorted(rows):
            old, new = rows[key]
            lines.append(f"| {escape_cell(key)} | {_cell(old)} | {_cell(new)} |")
    extra = _varied(diff.varied_here, "Varied across these runs")
    extra += _varied(diff.varied_parent, "Varied across the parent's runs")
    if extra:
        lines += ["", *extra]
    return "\n".join(lines) + "\n"


def render_runs(run_ids: Sequence[str], varied: Sequence[str]) -> str:
    lines = [f"Runs: {', '.join(run_ids)}.", *_varied(varied, "Varied across these runs")]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 5: Add `tracker diff` to `labbrain/cli.py`**

Above `# --- parser ---`:

```python
def cmd_tracker_diff(args: argparse.Namespace) -> int:
    from labbrain.experiments import config_diff, parent_run_ids, render_setup
    from labbrain.trackers import get_adapter
    from labbrain.vault import Vault

    root, config = _config(args)
    vault = Vault.load(root, config)
    adapter = get_adapter(config, root)
    parent = [r["config"] for r in adapter.fetch(parent_run_ids(vault, args.parent))]
    child = [r["config"] for r in adapter.fetch(args.runs)]
    print(render_setup(config_diff(args.parent, parent, child, config.hash_ignore)), end="")
    return EXIT_OK
```

In `build_parser`, directly after the `tracker fetch` block:

```python
    p = tracker_sub.add_parser("diff", help="config diff against a parent experiment", parents=[common])
    p.add_argument("runs", nargs="+", metavar="RUN")
    p.add_argument("--parent", required=True, help="experiment ID whose runs are the baseline")
    p.set_defaults(func=cmd_tracker_diff)
```

- [ ] **Step 6: Measure coverage**

In `pyproject.toml`, add `"*/labbrain/experiments.py",` to `[tool.coverage.report] include`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiments.py tests/test_cli.py -v`
Expected: PASS. The existing `config-hash` tests prove that the `is_ignored` refactor kept hashes identical.

- [ ] **Step 8: Full suite, coverage and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest --cov --cov-fail-under=85`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add labbrain/experiments.py labbrain/confighash.py labbrain/cli.py tests/test_experiments.py pyproject.toml
git commit -m "feat: add tracker diff with varied-key handling

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `labbrain exp record`

**Files:**
- Modify: `labbrain/experiments.py` (record pipeline)
- Modify: `labbrain/scaffold.py` (`skeleton(section_text=)`, `create(extra=, section_text=)`)
- Modify: `labbrain/cli.py` (`cmd_exp_record`, the `exp` parser)
- Test: `tests/test_exp_record.py`

**Interfaces:**
- Consumes:
  - Task 1: `scaffold.create`, `scaffold.one_line`.
  - Task 2: `_finish` (CLI).
  - Task 3: `get_adapter`, `describe`, `TrackerAdapter`, `RunRecord`, `resolve_config_path`.
  - Task 4: `code_sha`, `CodeError`.
  - Task 6: `config_diff`, `parent_run_ids`, `render_setup`, `render_runs`, `split_common`, `escape_cell`, `RecordError`.
  - Existing: `notes.update_frontmatter`, `notes.atomic_write`, `notes.split_frontmatter`.
- Produces:
  - `skeleton(..., section_text: Mapping[str, str] | None = None)`;
  - `create(..., extra: Mapping[str, Any] | None = None, section_text: Mapping[str, str] | None = None)`;
  - from `labbrain.experiments`:
    - `RecordRequest` (dataclass);
    - `record(root, config, req, adapter=None) -> Path`;
    - `run_status(statuses) -> str`;
    - `split_of(name) -> str | None`;
    - `render_results(metrics) -> str`;
    - `append_to_section(text, heading, block) -> str`;
  - CLI `exp record`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_exp_record.py`:

```python
"""`labbrain exp record`: experiment notes from tracker runs."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from helpers import RUNS_FIXTURE, commit_all, copy_fixture, copy_runs, git

from labbrain.cli import main
from labbrain.experiments import append_to_section, run_status, split_of
from labbrain.notes import parse_note, update_frontmatter

PARENT = "EXP-20260910-label-smoothing"
HYPOTHESIS = "A lower learning rate with dropout beats label smoothing alone."


@pytest.fixture(autouse=True)
def _no_author_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LABBRAIN_AUTHOR", raising=False)


@pytest.fixture
def runs_vault(vault_dir: Path) -> Path:
    copy_runs(vault_dir)
    return vault_dir


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def record(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    return run(capsys, "exp", "record", *argv)


def variant(vault: Path, run_id: str, *, base: str = "run-c1", drop: str = "", meta: str = "") -> None:
    """A copy of a fixture run, optionally without one config line prefix, or with new meta."""
    target = vault / "runs" / run_id
    shutil.copytree(RUNS_FIXTURE / base, target)
    if drop:
        cfg = target / "config.yaml"
        lines = cfg.read_text().splitlines(keepends=True)
        out, skipping = [], False
        for line in lines:
            if line.startswith(drop):
                skipping = True
                continue
            if skipping and line.startswith(" "):
                continue
            skipping = False
            out.append(line)
        cfg.write_text("".join(out))
    if meta:
        (target / "meta.json").write_text(meta)


def new_experiments(vault: Path) -> list[Path]:
    return sorted((vault / "experiments").glob("EXP-20261015-*.md"))


def test_record_done_from_child_runs(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = record(
        capsys, "run-c1", "run-c2", "--author", "claude", "--title", "Lower LR with dropout",
        "--parent", PARENT, "--hypothesis", HYPOTHESIS,
        "--summary", "Two folds of the lower-LR dropout variant.",
    )
    assert code == 0, err
    path = Path(out.strip())
    assert path.is_absolute() and path.name == "EXP-20261015-lower-lr-with-dropout.md"
    data = parse_note(path, runs_vault).data
    assert data is not None
    assert data["status"] == "done"
    assert data["protocol"] == "EVAL-v2" and data["dataset"] == "DS-20260801-main-split"
    assert data["tracker"] == {"backend": "local", "run_ids": ["run-c1", "run-c2"], "url": None}
    assert data["code"] == {"repo": None, "sha": "5d6e7f8", "dirty": False}
    assert data["config_hash"] is None
    assert data["links"] == [PARENT]
    assert data["hypothesis"] == HYPOTHESIS
    assert [(m["name"], m["split"], m["run_id"]) for m in data["metrics"]] == [
        ("epoch", None, "run-c1"), ("test.auroc", "test", "run-c1"), ("val.auroc", "val", "run-c1"),
        ("epoch", None, "run-c2"), ("test.auroc", "test", "run-c2"), ("val.auroc", "val", "run-c2"),
    ]
    assert all(m["as_of"] == date(2026, 10, 15) for m in data["metrics"])
    text = path.read_text()
    assert "## For future agents\n\nTwo folds of the lower-LR dropout variant.\n" in text
    assert f"## Hypothesis\n\n{HYPOTHESIS}\n" in text
    assert "| optim.lr | 0.001 | 0.0003 |" in text
    assert "Varied across these runs: data.fold." in text
    assert "| test.auroc | 0.85 | test | run-c1 |" in text
    assert run(capsys, "validate", str(path))[0] == 0


def test_without_parent_setup_lists_the_runs(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = record(capsys, "run-c1", "run-c2", "--author", "claude", "--title", "Two folds")
    assert code == 0
    assert "Runs: run-c1, run-c2.\nVaried across these runs: data.fold.\n" in Path(out.strip()).read_text()


@pytest.mark.parametrize("flag", ["--parent", "--link"])
def test_unknown_parent_or_link_writes_nothing(
    runs_vault: Path, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    code, _, err = record(capsys, "run-c1", "--author", "claude", "--title", "X", flag, "EXP-20990101-nope")
    assert code == 2 and "no note with ID" in err
    assert new_experiments(runs_vault) == []


def test_done_gate_missing_protocol(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = record(capsys, "run-noproto", "--author", "claude", "--title", "No protocol")
    assert code == 2
    assert err == (
        "labbrain: protocol required to record finished runs: "
        "pass --protocol or set eval.protocol in the run config\n"
    )
    assert new_experiments(runs_vault) == []


def test_done_gate_missing_dataset(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-nodata", drop="data:")
    code, _, err = record(capsys, "run-nodata", "--author", "claude", "--title", "No dataset")
    assert code == 2
    assert "dataset required to record finished runs: pass --dataset or set data.dataset" in err
    assert new_experiments(runs_vault) == []


def test_done_gate_missing_both(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-bare", base="run-noproto", drop="data:")
    code, _, err = record(capsys, "run-bare", "--author", "claude", "--title", "Bare")
    assert code == 2
    assert (
        "protocol and dataset required to record finished runs: pass --protocol/--dataset"
        " or set eval.protocol/data.dataset in the run config"
    ) in err


def test_explicit_protocol_satisfies_the_gate(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = record(
        capsys, "run-noproto", "--author", "claude", "--title", "Given", "--protocol", "EVAL-v2"
    )
    assert code == 0
    assert parse_note(Path(out.strip()), runs_vault).data["protocol"] == "EVAL-v2"


def test_unknown_protocols_are_not_echoed(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = record(
        capsys, "run-noproto", "--author", "claude", "--title", "X", "--protocol", "EVAL-v9"
    )
    assert code == 2 and err == "labbrain: protocol not found\n"
    variant(runs_vault, "run-v7", base="run-noproto")
    cfg = runs_vault / "runs" / "run-v7" / "config.yaml"
    cfg.write_text(cfg.read_text() + "eval:\n  protocol: EVAL-v7\n")
    code, _, err = record(capsys, "run-v7", "--author", "claude", "--title", "X")
    assert code == 2 and "EVAL-v7" not in err


def test_unknown_dataset(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = record(
        capsys, "run-c1", "--author", "claude", "--title", "X", "--dataset", "DS-20990101-nope"
    )
    assert code == 2 and err == "labbrain: dataset not found\n"


def test_runs_disagree_on_protocol(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-v1", base="run-noproto")
    cfg = runs_vault / "runs" / "run-v1" / "config.yaml"
    cfg.write_text(cfg.read_text() + "eval:\n  protocol: EVAL-v1\n")
    code, _, err = record(capsys, "run-c1", "run-v1", "--author", "claude", "--title", "Mixed")
    assert code == 2 and err == "labbrain: runs disagree on protocol; pass --protocol\n"
    code, _, _ = record(
        capsys, "run-c1", "run-v1", "--author", "claude", "--title", "Mixed", "--protocol", "EVAL-v2"
    )
    assert code == 0


@pytest.mark.parametrize(("run_id", "status"), [("run-failed", "failed"), ("run-nometrics", "running")])
def test_failed_and_running_runs(
    runs_vault: Path, capsys: pytest.CaptureFixture[str], run_id: str, status: str
) -> None:
    code, out, _ = record(capsys, run_id, "--author", "claude", "--title", f"Status {status}")
    assert code == 0
    path = Path(out.strip())
    assert parse_note(path, runs_vault).data["status"] == status
    assert run(capsys, "validate", str(path))[0] == 0


def test_running_runs_need_no_protocol(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-early", base="run-noproto")
    (runs_vault / "runs" / "run-early" / "metrics.json").unlink()
    code, out, _ = record(capsys, "run-early", "--author", "claude", "--title", "Early")
    assert code == 0
    data = parse_note(Path(out.strip()), runs_vault).data
    assert data["status"] == "running" and data["protocol"] is None


def test_disagreeing_shas_record_no_code(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-other-sha", meta='{"git_sha": "abcdef1"}')
    (runs_vault / "runs" / "run-other-sha" / "metrics.json").write_text('{"m": 1}')
    code, out, _ = record(capsys, "run-c1", "run-other-sha", "--author", "claude", "--title", "Two shas")
    assert code == 0 and parse_note(Path(out.strip()), runs_vault).data["code"] is None


def test_a_dirty_run_marks_code_dirty(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    variant(runs_vault, "run-dirty", meta='{"git_sha": "5d6e7f8", "git_dirty": true}')
    code, out, _ = record(capsys, "run-c1", "run-dirty", "--author", "claude", "--title", "Dirty")
    assert code == 0
    assert parse_note(Path(out.strip()), runs_vault).data["code"]["dirty"] is True


def test_code_falls_back_to_the_code_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code_repo = tmp_path / "code"
    shutil.copytree(RUNS_FIXTURE, code_repo / "runs")
    git(code_repo, "init", "-q", "-b", "main")
    commit_all(code_repo)
    vault = copy_fixture(tmp_path / "vault")
    cfg = vault / ".labbrain" / "config.yaml"
    cfg.write_text(cfg.read_text() + "code_repo: ../code\n")
    monkeypatch.setenv("LABBRAIN_NOW", "2026-10-15T12:00:00")
    monkeypatch.setenv("LABBRAIN_VAULT", str(vault))
    code, out, _ = record(
        capsys, "run-noproto", "--author", "claude", "--title", "From repo", "--protocol", "EVAL-v2"
    )
    assert code == 0
    sha = git(code_repo, "rev-parse", "HEAD").strip()
    assert parse_note(Path(out.strip()), vault).data["code"] == {
        "repo": "../code", "sha": sha, "dirty": False,
    }


def test_into_fills_a_planned_note(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, out, _ = run(
        capsys, "new", "experiment", "--title", "Planned lower LR", "--author", "claude",
        "--summary", "Planned.",
    )
    planned = Path(out.strip())
    planned.write_text(
        planned.read_text().replace(
            "## Setup\n", "## Setup\n\nPlanned: lower the learning rate and add dropout.\n"
        )
    )
    update_frontmatter(planned, {"hypothesis": "Lower LR helps."})
    code, out, err = record(
        capsys, "run-c1", "run-c2", "--author", "claude", "--into", planned.stem, "--parent", PARENT
    )
    assert code == 0, err
    assert Path(out.strip()).resolve() == planned.resolve()
    data = parse_note(planned, runs_vault).data
    assert data["status"] == "done" and data["title"] == "Planned lower LR"
    assert data["hypothesis"] == "Lower LR helps." and data["links"] == [PARENT]
    text = planned.read_text()
    setup = text.index("## Setup")
    assert setup < text.index("Planned: lower the learning rate") < text.index("Config diff against")
    assert text.index("Config diff against") < text.index("## Results") < text.index("| test.auroc |")
    assert run(capsys, "validate", str(planned))[0] == 0


def test_into_refuses_finished_notes(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = record(capsys, "run-c1", "--author", "claude", "--into", "EXP-20260901-baseline")
    assert code == 2
    assert err == (
        "labbrain: EXP-20260901-baseline is done; only planned or running experiments can be filled in\n"
    )


def test_into_unknown_note(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = record(capsys, "run-c1", "--author", "claude", "--into", "EXP-20990101-nope")
    assert code == 2 and "no experiment with ID" in err


def test_title_and_into_are_exclusive(runs_vault: Path) -> None:
    for extra in (["--title", "X", "--into", PARENT], []):
        with pytest.raises(SystemExit) as info:
            main(["exp", "record", "run-c1", "--author", "claude", *extra])
        assert info.value.code == 2


def test_record_with_finish(runs_vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = record(
        capsys, "run-c1", "--author", "claude", "--title", "Finished in one call",
        "--finish", "exp-log: Finished in one call",
    )
    assert code == 0
    assert "[[EXP-20261015-finished-in-one-call]]" in (runs_vault / "index.md").read_text()
    assert "exp-log: Finished in one call" in (runs_vault / "log" / "2026-10-15.md").read_text()


@pytest.mark.parametrize(
    ("name", "split"),
    [("test/auroc", "test"), ("val.loss", "val"), ("validation.f1", "validation"),
     ("valid.acc", "valid"), ("train.loss", "train"), ("auroc", None), ("test", None),
     ("testing.auroc", None)],
)
def test_split_of(name: str, split: str | None) -> None:
    assert split_of(name) == split


def test_run_status() -> None:
    assert run_status(["finished", "failed", "running"]) == "failed"
    assert run_status(["finished", "unknown"]) == "running"
    assert run_status(["finished", "finished"]) == "done"


def test_append_to_section_respects_fences_and_line_endings() -> None:
    text = (
        "---\nid: x\n---\n## Hypothesis\n\n```\n## Setup\n```\n\n## Setup\n\nPlan.\n\n## Results\n"
    )
    out = append_to_section(text, "Setup", "Block.\n")
    assert out == (
        "---\nid: x\n---\n## Hypothesis\n\n```\n## Setup\n```\n\n"
        "## Setup\n\nPlan.\n\nBlock.\n\n## Results\n"
    )
    crlf = "---\r\nid: x\r\n---\r\n## Setup\r\n## Results\r\n"
    assert append_to_section(crlf, "Setup", "Block.\n") == (
        "---\r\nid: x\r\n---\r\n## Setup\r\n\r\nBlock.\r\n\r\n## Results\r\n"
    )
```

Run `uv run ruff format tests/test_exp_record.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_exp_record.py -v`
Expected: FAIL with `ImportError: cannot import name 'append_to_section'`.

- [ ] **Step 3: Extend `labbrain/scaffold.py`**

Add the `section_text` parameter to `skeleton`, after `status`:

```python
    section_text: Mapping[str, str] | None = None,
```

and replace its line `sections += [f"## {section}\n" for section in REQUIRED_SECTIONS[note_type]]` with:

```python
    for section in REQUIRED_SECTIONS[note_type]:
        text = (section_text or {}).get(section, "").strip("\n")
        sections.append(f"## {section}\n\n{text}\n" if text else f"## {section}\n")
```

Add two parameters to `create`, after `status`:

```python
    extra: Mapping[str, Any] | None = None,
    section_text: Mapping[str, str] | None = None,
```

Inside the loop, merge them in:

- rename the loop's local dict from `extra` to `fields`;
- after the protocol, handoff and literature branches, add `fields.update(extra or {})`;
- pass `extra=fields, section_text=section_text` to `skeleton`.

`extra` may set `status`. That is how `exp record` writes `done` and `failed`; the `--status` allowlist applies only to the `status` argument.

- [ ] **Step 4: Append the record pipeline to `labbrain/experiments.py`**

Add these imports at the top: `import re`, `from dataclasses import field`, `from datetime import date, datetime`, `from pathlib import Path`, `from typing import get_args`, and `from ruamel.yaml.comments import CommentedMap`. Add these classes: `from labbrain.notes import Note, atomic_write, split_frontmatter, update_frontmatter`, `from labbrain.schema import ExperimentNote`, `from labbrain.trackers.base import RunRecord, TrackerAdapter` and `from labbrain.vault import Config, Vault, resolve_config_path`. Then append:

```python
SPLITS = frozenset({"train", "val", "valid", "validation", "test"})
FILLABLE = ("planned", "running")
_EXPERIMENT_STATUSES = frozenset(get_args(ExperimentNote.model_fields["status"].annotation))


@dataclass
class RecordRequest:
    run_ids: list[str]
    author: str
    now: datetime
    title: str | None = None
    into: str | None = None
    parent: str | None = None
    protocol: str | None = None
    dataset: str | None = None
    hypothesis: str | None = None
    summary: str = ""
    links: list[str] = field(default_factory=list)


def split_of(name: str) -> str | None:
    head = re.split(r"[/.]", name, maxsplit=1)[0]
    return head if head in SPLITS and head != name else None


def run_status(statuses: Iterable[str]) -> str:
    statuses = list(statuses)
    if "failed" in statuses:
        return "failed"
    if any(s in ("running", "unknown") for s in statuses):
        return "running"
    return "done"


def _flow(data: Mapping[str, Any]) -> CommentedMap:
    mapping = CommentedMap(data)
    mapping.fa.set_flow_style()
    return mapping


def _status_label(value: str | None) -> str:
    return value if value in _EXPERIMENT_STATUSES else "<invalid status>"


def _shared(values: Iterable[str | None], what: str) -> str | None:
    found = {v for v in values if v}
    if len(found) > 1:
        raise RecordError(f"runs disagree on {what}; pass --{what}")
    return found.pop() if found else None


def _resolve(given: str | None, planned: str | None, runs: Iterable[str | None], what: str) -> str | None:
    if given:
        return given
    if planned:
        return planned
    return _shared(runs, what)


def _require(vault: Vault, note_id: str | None, note_type: str) -> None:
    if note_id is None:
        return
    note = vault.get(note_id)
    if note is None or note.type != note_type:
        raise RecordError(f"{note_type} not found")


def _fillable(vault: Vault, note_id: str) -> Note:
    note = vault.get(note_id)
    if note is None or note.type != "experiment":
        raise RecordError(f"no experiment with ID {display_id(note_id, vault.notes)}")
    status = note.get_str("status")
    if status not in FILLABLE:
        raise RecordError(
            f"{note_id} is {_status_label(status)}; only planned or running experiments can be filled in"
        )
    return note


def resolve_code(records: Sequence[RunRecord], config: Config, root: Path) -> CommentedMap | None:
    from labbrain.codeinfo import CodeError, code_sha

    repo = config.code_repo.strip() or None
    shas = {r["git_sha"] for r in records if r["git_sha"]}
    dirty = any(r["git_dirty"] for r in records)
    if len(shas) > 1:
        return None
    if shas:
        return _flow({"repo": repo, "sha": shas.pop(), "dirty": dirty})
    if repo is None:
        return None
    try:
        info = code_sha(resolve_config_path(root, repo), exclude=root)
    except CodeError:
        return None
    return _flow({"repo": repo, "sha": info.sha, "dirty": dirty or info.dirty})


def build_metrics(described: Sequence[Mapping[str, Any]], today: date) -> list[CommentedMap]:
    return [
        _flow(
            {
                "name": name,
                "value": d["headline"][name],
                "split": split_of(name),
                "run_id": d["run_id"],
                "as_of": today,
            }
        )
        for d in described
        for name in sorted(d["headline"])
    ]


def render_results(metrics: Sequence[Mapping[str, Any]]) -> str:
    if not metrics:
        return "No headline metrics recorded.\n"
    lines = ["| metric | value | split | run |", "| --- | --- | --- | --- |"]
    for m in metrics:
        lines.append(
            f"| {escape_cell(m['name'])} | {json.dumps(m['value'])} | {m['split'] or '—'}"
            f" | {escape_cell(m['run_id'])} |"
        )
    return "\n".join(lines) + "\n"


def append_to_section(text: str, heading: str, block: str) -> str:
    """`text` with `block` added at the end of its `## heading` section, fences respected."""
    _, _, body_line = split_frontmatter(text)
    lines = text.splitlines(keepends=True)
    start, end, fence = None, len(lines), False
    for i in range(body_line - 1, len(lines)):
        stripped = lines[i].lstrip()
        if stripped.startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence or not lines[i].startswith("## "):
            continue
        if start is not None:
            end = i
            break
        if lines[i][3:].strip() == heading:
            start = i
    if start is None:
        raise RecordError(f"note has no ## {heading} section")
    newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
    head = lines[:end]
    while len(head) - 1 > start and not head[-1].strip():
        head.pop()
    if not head[-1].endswith(("\n", "\r\n")):
        head[-1] += newline
    insertion = [newline, *(row + newline for row in block.rstrip("\n").split("\n"))]
    tail = lines[end:]
    if tail:
        insertion.append(newline)
    return "".join(head + insertion + tail)


def _fill(note: Note, fields: dict[str, Any], links: list[str], setup: str, results: str) -> Path:
    merged = list(dict.fromkeys([*note.get_list("links"), *links]))
    with open(note.path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    text = append_to_section(text, "Setup", setup)
    text = append_to_section(text, "Results", results)
    atomic_write(note.path, text)
    update_frontmatter(note.path, {**fields, "links": merged})
    return note.path


def record(
    root: Path, config: Config, req: RecordRequest, adapter: TrackerAdapter | None = None
) -> Path:
    """Create an experiment note from runs, or fill in a planned or running one."""
    from labbrain.scaffold import create, one_line
    from labbrain.trackers import describe, get_adapter

    vault = Vault.load(root, config)
    for note_id in [req.parent, *req.links]:
        if note_id and vault.get(note_id) is None:
            raise RecordError(f"no note with ID {display_id(note_id, vault.notes)}")
    target = _fillable(vault, req.into) if req.into else None
    adapter = adapter or get_adapter(config, root)
    records = adapter.fetch(req.run_ids)
    described = [describe(r, config) for r in records]
    protocol = _resolve(
        req.protocol,
        target.get_str("protocol") if target else None,
        (d["protocol"] for d in described),
        "protocol",
    )
    dataset = _resolve(
        req.dataset,
        target.get_str("dataset") if target else None,
        (d["dataset"] for d in described),
        "dataset",
    )
    _require(vault, protocol, "protocol")
    _require(vault, dataset, "dataset")
    status = run_status(r["status"] for r in records)
    missing = [w for w, v in (("protocol", protocol), ("dataset", dataset)) if not v]
    if status == "done" and missing:
        keys = {"protocol": config.protocol_key, "dataset": config.dataset_key}
        raise RecordError(
            f"{' and '.join(missing)} required to record finished runs: "
            f"pass {'/'.join('--' + w for w in missing)} "
            f"or set {'/'.join(keys[w] for w in missing)} in the run config"
        )
    hashes = {d["config_hash"] for d in described}
    url = next((r["url"] for r in records if r["url"]), None)
    today = req.now.date()
    metrics = build_metrics(described, today)
    fields: dict[str, Any] = {
        "updated": today,
        "status": status,
        "protocol": protocol,
        "tracker": _flow({"backend": config.tracker.backend, "run_ids": list(req.run_ids), "url": url}),
        "code": resolve_code(records, config, root),
        "config_hash": hashes.pop() if len(hashes) == 1 else None,
        "dataset": dataset,
        "metrics": metrics,
    }
    hypothesis = one_line(req.hypothesis or "")
    if hypothesis:
        fields["hypothesis"] = hypothesis
    if req.parent:
        parent = [r["config"] for r in adapter.fetch(parent_run_ids(vault, req.parent))]
        diff = config_diff(req.parent, parent, [r["config"] for r in records], config.hash_ignore)
        setup = render_setup(diff)
    else:
        _, varied = split_common([r["config"] for r in records], config.hash_ignore)
        setup = render_runs(req.run_ids, varied)
    results = render_results(metrics)
    links = list(dict.fromkeys(i for i in [req.parent, *req.links] if i))
    if target is not None:
        return _fill(target, fields, links, setup, results)
    return create(
        root,
        config,
        "experiment",
        title=req.title or "",
        author=req.author,
        now=req.now,
        links=links,
        summary=req.summary,
        extra=fields,
        section_text={"Hypothesis": hypothesis, "Setup": setup, "Results": results},
    )
```

- [ ] **Step 5: Add `exp record` to `labbrain/cli.py`**

Above `# --- parser ---`:

```python
def cmd_exp_record(args: argparse.Namespace) -> int:
    from labbrain.experiments import RecordRequest, record

    author = _author(args)
    root, config = _config(args)
    request = RecordRequest(
        run_ids=args.runs,
        author=author,
        now=_now(args.at),
        title=args.title,
        into=args.into,
        parent=args.parent,
        protocol=args.protocol,
        dataset=args.dataset,
        hypothesis=args.hypothesis,
        summary=args.summary,
        links=args.link,
    )
    path = record(root, config, request)
    print(path)
    if args.finish:
        return _finish(args, [path], args.finish, author)
    return EXIT_OK
```

Above `return parser`:

```python
    exp = add("exp", "experiment commands")
    exp_sub = exp.add_subparsers(dest="exp_command", required=True)
    p = exp_sub.add_parser("record", help="write an experiment note from runs", parents=[common])
    p.add_argument("runs", nargs="+", metavar="RUN")
    p.add_argument("--author", default=None)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--title", help="create a new experiment with this title")
    target.add_argument("--into", help="fill in this planned or running experiment")
    p.add_argument("--parent", help="experiment whose runs these change (config diff)")
    p.add_argument("--protocol", help="protocol ID (default: the runs' protocol key)")
    p.add_argument("--dataset", help="dataset ID (default: the runs' dataset key)")
    p.add_argument("--hypothesis")
    p.add_argument("--summary", default="", help="one line for the For-future-agents block")
    p.add_argument("--link", action="append", default=[], help="ID to put in `links` (repeatable)")
    p.add_argument("--at", default=None, help="ISO datetime to use instead of now")
    p.add_argument("--finish", default="", help="then run `finish` with this log text")
    p.set_defaults(func=cmd_exp_record)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_exp_record.py tests/test_new_flags.py tests/test_scaffold.py -v`
Expected: PASS.

If ruamel renders a flow `CommentedMap` value differently from what `parse_note(...).data` expects, the data is still a plain dict after parsing, so fix the writer and not the test. The YAML-1.1 quoting comes from `_yaml11_safe`, so a SHA such as `1234567` stays a string.

- [ ] **Step 7: Full suite, coverage and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest --cov --cov-fail-under=85`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add labbrain/experiments.py labbrain/scaffold.py labbrain/cli.py tests/test_exp_record.py
git commit -m "feat: add exp record with the protocol and dataset gate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Plugin manifests, version 0.2.0 and the six skills

**Files:**
- Create: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- Create: `skills/brain-core/SKILL.md`, `skills/idea/SKILL.md`, `skills/exp-log/SKILL.md`, `skills/decide/SKILL.md`, `skills/handoff/SKILL.md`, `skills/brief/SKILL.md`
- Modify: `pyproject.toml` (`version = "0.2.0"`, `[tool.uv] cache-keys`), `labbrain/__init__.py` (`__version__ = "0.2.0"`), `uv.lock` (via `uv lock`)
- Test: `tests/test_plugin_manifest.py`

**Interfaces:**
- Consumes: every CLI subcommand from Tasks 1–7 (`vault root`, `config`, `new`, `finish`, `list`, `tracker fetch`, `exp record`, `brief`); `cli.build_parser()`.
- Produces: the installable plugin. Task 9's smoke tests invoke `/lab-brain:idea`, `/lab-brain:exp-log` and `/lab-brain:brief`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_plugin_manifest.py`:

```python
"""The plugin manifests and skills stay consistent with the engine they call."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from labbrain import __version__
from labbrain.cli import build_parser

REPO = Path(__file__).resolve().parents[1]
ENGINE = 'uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain'
ENGINE_RULES = (
    'Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)',
    "Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)",
)
SKILLS = ("brain-core", "brief", "decide", "exp-log", "handoff", "idea")
TAKES_ARGUMENTS = ("decide", "exp-log", "idea")
COMMAND = re.compile(r"\blabbrain ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")


def manifest(name: str) -> dict[str, Any]:
    return json.loads((REPO / ".claude-plugin" / name).read_text(encoding="utf-8"))


def skill(name: str) -> tuple[dict[str, Any], str]:
    text = (REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), name
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end]), text[end + 5 :]


def subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def test_manifests_agree_with_pyproject() -> None:
    plugin, market = manifest("plugin.json"), manifest("marketplace.json")
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert plugin["name"] == market["name"] == "lab-brain"
    assert plugin["version"] == project["version"] == __version__ == "0.2.0"
    assert plugin["license"] == project["license"]
    assert plugin["author"]["name"] == project["authors"][0]["name"] == market["owner"]["name"]
    assert market["description"].strip()
    [entry] = market["plugins"]
    assert entry["name"] == plugin["name"]
    assert entry["source"] in ("./", ".")
    assert "version" not in entry


def test_skill_directories_are_exactly_the_six() -> None:
    assert sorted(p.name for p in (REPO / "skills").iterdir() if p.is_dir()) == sorted(SKILLS)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_frontmatter(name: str) -> None:
    meta, body = skill(name)
    assert meta["name"] == name
    assert isinstance(meta["description"], str) and meta["description"].strip()
    assert len(meta["description"]) <= 1536
    assert "disable-model-invocation" not in meta
    rules = meta["allowed-tools"]
    rules = rules if isinstance(rules, list) else [r.strip() for r in rules.split(",")]
    for rule in ENGINE_RULES:
        assert rule in rules, (name, rule)
    if name in TAKES_ARGUMENTS:
        assert meta.get("argument-hint") and "$ARGUMENTS" in body


@pytest.mark.parametrize("name", SKILLS)
def test_skill_commands_exist_in_the_cli(name: str) -> None:
    _, body = skill(name)
    top = subparsers(build_parser())
    found = COMMAND.findall(body)
    assert found, name
    for first, second in found:
        assert first in top, (name, first)
        nested = subparsers(top[first])
        if nested:
            assert second in nested, (name, first, second)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_commands_follow_the_shell_rules(name: str) -> None:
    _, body = skill(name)
    assert "$(" not in body
    for match in re.finditer(r"labbrain ", body):
        assert body[: match.start()].endswith('uvx --from "${CLAUDE_PLUGIN_ROOT}" '), (
            name,
            body[max(0, match.start() - 40) : match.end() + 20],
        )


def test_brain_core_is_short() -> None:
    lines = (REPO / "skills" / "brain-core" / "SKILL.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 80
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_plugin_manifest.py -v`
Expected: FAIL with `FileNotFoundError` for `.claude-plugin/plugin.json`.

- [ ] **Step 3: Bump the version and add uv cache keys**

- In `pyproject.toml`, set `version = "0.2.0"`.
- In `labbrain/__init__.py`, set `__version__ = "0.2.0"`.
- Append to `pyproject.toml`:

```toml
[tool.uv]
# uvx --from <checkout> (how the plugin runs the engine) rebuilds only when these change.
cache-keys = [{ file = "pyproject.toml" }, { file = "labbrain/**/*.py" }]
```

Then run `uv lock`. Expected: `uv.lock` updates the `labbrain` version only.

- [ ] **Step 4: Create the manifests**

`.claude-plugin/plugin.json`:

```json
{
  "name": "lab-brain",
  "version": "0.2.0",
  "description": "Skills for lab-brain research vaults: capture ideas, log experiments, record decisions, hand off sessions.",
  "author": { "name": "jorgebotas" },
  "repository": "https://github.com/jorgebotas/lab-brain",
  "license": "MIT"
}
```

`.claude-plugin/marketplace.json`:

```json
{
  "name": "lab-brain",
  "description": "Single-plugin marketplace for the lab-brain engine.",
  "owner": { "name": "jorgebotas" },
  "plugins": [{ "name": "lab-brain", "source": "./" }]
}
```

- [ ] **Step 5: Create `skills/brain-core/SKILL.md`**

````markdown
---
name: brain-core
description: Conventions for working in a lab-brain research vault. Use in any session whose working directory is inside a lab-brain vault (a folder with .labbrain/config.yaml at or above it), or whenever the user talks about the vault's experiments, ideas, decisions, protocols, claims or handoffs.
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Working in a lab-brain vault

The engine command is `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain`. Type it in full every time. Never store it in a shell variable or use command substitution. Pass any text that comes from the user inside single quotes, writing a `'` inside it as `'\''`.

## Orient first

1. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain vault root`. If it fails, this is not a vault; ignore the rest of this skill.
2. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain config` and note `protected_data`, `data_paths`, `min_cell_size` and `search`.
3. Read `index.md` at the vault root before searching, then search with ripgrep. Use the qmd MCP server only when `search` is `qmd`.

## Write rules

| Folder | Rule |
| --- | --- |
| `raw/` | Never modify or delete. |
| `experiments/` | Append-only; once done, only `status` and `superseded_by` change. |
| `protocols/` | A new version is a new file; a version an experiment uses is frozen. |
| `claims/` | Editable; every edit appends a line to `## History`. |
| `ideas/inbox/` | Create-only; consolidated ideas move to `ideas/archive/` with `git mv`. |
| `concepts/` | Rewritable; must cite their sources. |
| `decisions/` | Append-only; a reversal is a new decision with `supersedes`. |
| `literature/`, `datasets/` | One note per paper or extraction; datasets hold metadata, never data. |
| `manuscripts/` | Human-owned; write only under `manuscripts/_proposals/`. |
| `handoffs/` | Create-only, one per session. |
| `index.md`, `log/` | Written by the engine; never edit them by hand. |

Never delete a note. A correction is a new note with `supersedes: <ID>`.

## IDs, notes and numbers

- IDs come only from the engine (`new`, `new-id`, `exp record`) or from existing notes. Never make one up.
- Create notes with `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new <type> --title '<title>' --author claude --summary '<one line>'`. It prints the note's absolute path.
- After editing a note, run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <absolute path> --log '<what you did>' --author claude`. On exit 1, fix the reported fields and run it again.
- Every number copied into a note carries its source: a run ID, an `[[EXP-...]]` link, or `as of YYYY-MM-DD`.
- When the engine exits with an error, show its message to the user and stop. Never write the note by hand instead.

## Protected data (when `protected_data` is true)

- Never read, open, sample or print files under `data_paths`, even if asked. Ask the user to run the command and paste aggregate output.
- The vault holds aggregates only. Counts below `min_cell_size` are written as `<min_cell_size`.
- Never paste text that `phi-scan` matched into a note or a message.
- Example records in notes are synthetic and labelled as synthetic.

## Skills

- `/lab-brain:idea <text>`: capture an idea.
- `/lab-brain:exp-log <run-id...> [--parent EXP-ID] [--planned]`: log runs as an experiment.
- `/lab-brain:decide <summary>`: record a decision.
- `/lab-brain:handoff`: write the session handoff.
- `/lab-brain:brief`: show where the project stands.
````

- [ ] **Step 6: Create `skills/idea/SKILL.md`**

````markdown
---
name: idea
description: Capture an idea as a note in a lab-brain vault's ideas inbox. Use only when the user explicitly asks to capture, save or jot down an idea, for example with /lab-brain:idea.
argument-hint: <idea text>
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Capture an idea

The idea:

$ARGUMENTS

Capture it without asking any questions, in one Bash call.

1. Title: the idea's first sentence, cut to at most 80 characters, without a trailing period.
2. Tags: zero to three lowercase words that already appear in the idea. Do not invent topics.
3. Run this, with every value in single quotes (write a `'` inside a value as `'\''`). Repeat `--tag` once per tag, or leave it out:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new idea --title '<title>' --author claude --summary '<first sentence>' --body '<the full idea text>' --tag '<tag>' --finish 'idea: <title>'
   ```

4. The command prints the note's path, then the check results. Exit 0 means done: tell the user the note's ID in one line.
5. Exit 1 means the note failed validation. Read the findings, fix the note with the Edit tool, then run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log 'idea: <title>' --author claude`.
6. Exit 2 means the engine refused. Show its message and stop.

## Do not

- Do not ask questions, rewrite the idea, or add your own commentary to the note.
- Do not invent IDs, or tags that are not in the text.
- Do not use shell variables or command substitution.
- Do not edit `index.md` or the log by hand.
````

- [ ] **Step 7: Create `skills/exp-log/SKILL.md`**

````markdown
---
name: exp-log
description: Log tracker runs as an experiment note in a lab-brain vault. Use only when the user explicitly asks to log runs or an experiment, for example with /lab-brain:exp-log.
argument-hint: <run-id...> [--parent EXP-ID] [--planned]
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Log an experiment

Arguments: $ARGUMENTS

Run IDs are the arguments that are not flags. `--parent EXP-ID` names the experiment these runs change. `--planned` means the runs do not exist yet.

Pass every value from the user or the runs inside single quotes (write a `'` as `'\''`). Never use shell variables or command substitution.

## Runs that exist

1. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain tracker fetch <run-id...>`. It prints one JSON object per run, with `config`, `summary`, `status`, `tags`, `notes`, `protocol`, `dataset` and `headline`. If it exits non-zero, show the message and stop.
2. Hypothesis: use one only if the runs' `notes` or `tags` state it. Otherwise ask the user. Never invent one.
3. Protocol: use the runs' `protocol`. If it is null, ask the user, offering the IDs from `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain list --type protocol`. Never invent one.
4. Dataset: use the runs' `dataset`. If it is null, ask the user, offering the IDs from `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain list --type dataset`. If none fits, say so and suggest the user create one with `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new dataset --title '<title>' --author <their name>`. Do not log until it exists.
5. Record the experiment in one call. Leave out `--parent`, `--protocol` or `--dataset` when you have no value for them. If the user names a planned experiment for these runs, pass `--into <EXP-ID>` instead of `--title`:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain exp record <run-id...> --author claude --title '<short title>' --summary '<one line: what this experiment is>' --hypothesis '<hypothesis>' --parent <EXP-ID> --protocol <EVAL-ID> --dataset <DS-ID> --finish 'exp-log: <short title>'
   ```

6. The engine writes the setup diff, the results table and the stamped metrics itself; never retype them.
   - Exit 2 with "required to record finished runs" means a protocol or dataset is missing. Ask the user for it and run step 5 again.
   - Any other exit 2: show the message and stop.
   - Exit 1: fix the reported fields with the Edit tool, then run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log 'exp-log: <short title>' --author claude`.
7. Only if the user asked for an interpretation: add it under `## Interpretation` with the Edit tool, starting with `(agent interpretation, unreviewed)`. Then run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log 'exp-log: interpretation' --author claude`.
8. Report the note's ID, its status and the headline metrics in a few lines.

## Planned experiments (`--planned`)

1. Ask the user for the hypothesis if they have not given it.
2. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new experiment --title '<short title>' --author claude --summary '<one line>'`. It prints the note's path.
3. With the Edit tool, set `hypothesis:` in the frontmatter, write the hypothesis under `## Hypothesis`, and describe the planned setup under `## Setup`.
4. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log 'exp-log: planned <short title>' --author claude`.
5. Tell the user to run `/lab-brain:exp-log <run-id...> --into <EXP-ID>` once the runs exist.

## Do not

- Do not invent hypotheses, protocols, datasets or metric values.
- Do not copy metrics by hand, or edit the `metrics`, `tracker`, `code` or `config_hash` fields.
- Do not log each run of a group as its own note; one note covers the runs you were given.
- Do not change a `done` experiment; a correction is a new experiment with `supersedes`.
- Do not use shell variables or command substitution.
````

- [ ] **Step 8: Create `skills/decide/SKILL.md`**

````markdown
---
name: decide
description: Record a decision (an ADR) in a lab-brain vault's decisions folder. Use only when the user explicitly asks to record a decision or write an ADR, for example with /lab-brain:decide.
argument-hint: <decision summary>
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Record a decision

The decision: $ARGUMENTS

Pass every value inside single quotes (write a `'` as `'\''`). Never use shell variables or command substitution.

1. From the conversation, draft four sections: Context (why a decision was needed), Decision (what was decided), Alternatives considered, and Consequences.
2. If the conversation mentions no alternatives, ask the user which were considered. Do not invent them.
3. If this decision reverses or replaces an earlier one, find it with `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain list --type decision` and confirm its ID with the user.
4. Create the note. Use `--status proposed` instead of `accepted` when the user calls it a proposal. It prints the note's path:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new decision --title '<short title>' --author claude --summary '<one line: what was decided>' --status accepted
   ```

5. With the Edit tool, fill in `## Context`, `## Decision`, `## Alternatives considered` and `## Consequences`. If it replaces an earlier decision, set `supersedes: <ADR-ID>` in the frontmatter.
6. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log 'decide: <short title>' --author claude`. It also marks the superseded decision; never edit the old decision yourself. On exit 1, fix the reported fields and run it again.
7. Tell the user the decision's ID in one line.

## Do not

- Do not edit or delete an existing decision; a reversal is a new decision with `supersedes`.
- Do not invent alternatives or consequences that the conversation does not support.
- Do not use shell variables or command substitution.
````

- [ ] **Step 9: Create `skills/handoff/SKILL.md`**

````markdown
---
name: handoff
description: Write a session handoff note in a lab-brain vault. Use when the user asks for a handoff, when a working session in a vault is ending, when work passes to another agent, or when you are a subagent finishing delegated work in a vault.
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Write a handoff

Pass every value inside single quotes (write a `'` as `'\''`). Never use shell variables or command substitution.

1. Collect what changed:
   - In the vault: `git status --short` and `git diff --stat`.
   - Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain config --key code_repo`. If it prints a path, resolve it against the vault root from `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain vault root`. If that path exists, also run `git -C <path> status --short` and `git -C <path> diff --stat`.
2. Create the note. Use your own agent name for `--agent` if you were dispatched as a named subagent, otherwise `claude`. It prints the note's path:

   ```bash
   uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain new handoff --title '<what this session did, in a few words>' --author claude --agent claude --summary '<one line: what the next agent should know first>'
   ```

3. With the Edit tool:
   - set `session_goal:` to the session's goal in one line;
   - set `files_touched:` to the changed paths from step 1;
   - fill in `## Done`, `## In progress`, `## Blockers` and `## Next step for whoever picks this up`, linking notes as `[[ID]]`.
4. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain finish <path> --log 'handoff: <title>' --author claude`. On exit 1, fix the reported fields and run it again.
5. Tell the user the handoff's ID.

## Do not

- Do not edit an earlier handoff; write a new one.
- Do not list files that step 1 did not show.
- Do not paste secrets, data rows or text that `phi-scan` matched.
- Do not use shell variables or command substitution.
````

- [ ] **Step 10: Create `skills/brief/SKILL.md`**

````markdown
---
name: brief
description: Show where a lab-brain vault's project stands - recent handoffs, running and planned experiments, stale claims, open ideas and lint errors. Use when the user asks where things stand, for a status or a briefing, or at the start of a session in a vault.
allowed-tools:
  - Bash(uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain *)
  - Bash(uvx --from ${CLAUDE_PLUGIN_ROOT} labbrain *)
---

# Brief

1. Run `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain brief`.
2. Show its output to the user verbatim, in a code block.
3. If it exits non-zero, show the message and stop.

## Do not

- Do not write or change any note.
- Do not leave out the lint error count.
````

- [ ] **Step 11: Run the tests to verify they pass**

Run: `uv run pytest tests/test_plugin_manifest.py tests/test_meta.py -v`
Expected: PASS. `test_meta` PHI-scans the new skills and manifests. If it flags a line, reword it rather than adding an allowlist entry.

- [ ] **Step 12: Exercise the engine the way a skill does**

From the worktree root, run:

```bash
uvx --from "$PWD" labbrain --version
uvx --from "$PWD" labbrain --vault tests/fixtures/valid brief --short
```

Expected: `labbrain 0.2.0`, then the three-line short brief.

- [ ] **Step 13: Full suite and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: all pass. Check that no test hard-codes `0.1.0` as the engine version; the fixture's `engine_min_version: "0.1.0"` stays.

- [ ] **Step 14: Commit**

```bash
git add .claude-plugin skills tests/test_plugin_manifest.py pyproject.toml uv.lock labbrain/__init__.py
git commit -m "feat: add the lab-brain plugin manifests and six skills; version 0.2.0

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Smoke tests, the M4 gate script and CI jobs

**Files:**
- Create: `tests/smoke/harness.py`, `tests/smoke/conftest.py`, `tests/smoke/test_smoke_skills.py`
- Create: `scripts/m4-gate.sh` (executable)
- Create: `.github/workflows/smoke.yml`
- Modify: `.github/workflows/ci.yml` (add the `plugin-validate` job)
- Modify: `pyproject.toml` (pytest `smoke` marker, `addopts`)

**Interfaces:**
- Consumes:
  - Task 8's skills, invoked as `/lab-brain:<skill>`;
  - Task 3's `copy_runs`;
  - the CLI's `main` (for `validate` and `lint`);
  - the experiments module's `config_diff`, `parent_run_ids` and `render_setup`, plus `get_adapter`.
- Produces: `uv run pytest -m smoke`, `scripts/m4-gate.sh`, and the CI jobs `plugin-validate` and `smoke`.

Environment note: in this development sandbox the `claude` binary is not executable and no `ANTHROPIC_API_KEY` is set. Verify here that every smoke test **skips** cleanly and that the gate prints the checklist and exits 3. The real runs happen on the user's machine or in the manual workflow.

- [ ] **Step 1: Register the marker and deselect smoke by default**

In `[tool.pytest.ini_options]`, add a markers entry and `addopts`:

```toml
markers = [
    "slow: performance-budget tests",
    "network: needs network access (pre-commit try-repo)",
    "smoke: headless Claude Code runs; need claude plus ANTHROPIC_API_KEY or LABBRAIN_SMOKE_LOGIN=1",
]
addopts = ["-m", "not smoke"]
```

- [ ] **Step 2: Create the harness and its fixtures**

`tests/conftest.py` already exists, so the smoke helpers cannot be imported as `conftest`; they live in `tests/smoke/harness.py`. Pytest's default `prepend` import mode puts `tests/smoke/` on `sys.path` when it imports the conftest and the test module there, so `from harness import …` works.

`tests/smoke/harness.py`:

```python
"""Headless skill runs for the smoke tests (`uv run pytest -m smoke`).

By default each run is `claude --bare -p "/lab-brain:<skill> …" --plugin-dir <repo>`,
which needs ANTHROPIC_API_KEY. LABBRAIN_SMOKE_LOGIN=1 runs without --bare using your
normal login, with only project settings loaded. LABBRAIN_SMOKE_ALLOW_ENGINE=1 also
pre-approves the engine command, for when a skill's own allowed-tools is not honoured
under --permission-mode dontAsk.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
LOGIN = os.environ.get("LABBRAIN_SMOKE_LOGIN") == "1"
ALLOW_ENGINE = os.environ.get("LABBRAIN_SMOKE_ALLOW_ENGINE") == "1"


def run_skill(claude: str, vault: Path, prompt: str) -> dict[str, Any]:
    allowed = ["Read", "Edit", "Write"]
    if ALLOW_ENGINE:
        allowed += [f'Bash(uvx --from "{REPO}" labbrain *)', f"Bash(uvx --from {REPO} labbrain *)"]
    cmd = [claude]
    if not LOGIN:
        cmd.append("--bare")
    cmd += [
        "-p", prompt,
        "--plugin-dir", str(REPO),
        "--permission-mode", "dontAsk",
        "--allowedTools", *allowed,
        "--output-format", "json",
        "--max-turns", "15",
        "--max-budget-usd", "1",
    ]
    if LOGIN:
        cmd += ["--setting-sources", "project"]
    env = {**os.environ, "LABBRAIN_VAULT": str(vault)}
    env.pop("LABBRAIN_NOW", None)
    proc = subprocess.run(cmd, cwd=vault, env=env, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout)
```

`tests/smoke/conftest.py`:

```python
"""Fixtures for the smoke tests: skip without claude or credentials; a committed vault."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from harness import LOGIN
from helpers import commit_all, copy_fixture, copy_runs, git


@pytest.fixture
def claude_bin() -> str:
    path = shutil.which("claude")
    if path is None or not os.access(path, os.X_OK):
        pytest.skip("claude is not installed")
    if not (os.environ.get("ANTHROPIC_API_KEY") or LOGIN):
        pytest.skip("set ANTHROPIC_API_KEY, or LABBRAIN_SMOKE_LOGIN=1 to use your login")
    return path


@pytest.fixture
def smoke_vault(tmp_path: Path) -> Path:
    vault = copy_fixture(tmp_path / "vault")
    copy_runs(vault)
    git(vault, "init", "-q", "-b", "main")
    commit_all(vault, "smoke vault")
    return vault
```

Run `uv run ruff format tests/smoke`.

- [ ] **Step 3: Create `tests/smoke/test_smoke_skills.py`**

```python
"""Headless smoke tests: the installed skills drive the engine end to end."""

from __future__ import annotations

from pathlib import Path

import pytest
from harness import run_skill

from labbrain.cli import main
from labbrain.experiments import config_diff, parent_run_ids, render_setup
from labbrain.notes import parse_note
from labbrain.trackers import get_adapter
from labbrain.vault import Vault, load_config

pytestmark = pytest.mark.smoke
PARENT = "EXP-20260910-label-smoothing"


def notes_in(folder: Path) -> set[Path]:
    return set(folder.glob("*.md"))


def test_idea(claude_bin: str, smoke_vault: Path) -> None:
    inbox = smoke_vault / "ideas" / "inbox"
    before = notes_in(inbox)
    run_skill(claude_bin, smoke_vault, "/lab-brain:idea Don't forget cosine warmup on the small model")
    created = notes_in(inbox) - before
    assert len(created) == 1
    path = created.pop()
    assert "Don't forget" in path.read_text(encoding="utf-8")
    assert main(["--vault", str(smoke_vault), "validate", str(path)]) == 0
    assert main(["--vault", str(smoke_vault), "lint"]) == 0
    logs = "".join(p.read_text(encoding="utf-8") for p in (smoke_vault / "log").glob("*.md"))
    assert "idea:" in logs


def test_exp_log_with_parent(claude_bin: str, smoke_vault: Path) -> None:
    folder = smoke_vault / "experiments"
    before = notes_in(folder)
    run_skill(claude_bin, smoke_vault, f"/lab-brain:exp-log run-c1 run-c2 --parent {PARENT}")
    created = notes_in(folder) - before
    assert len(created) == 1
    path = created.pop()
    assert main(["--vault", str(smoke_vault), "validate", str(path)]) == 0
    data = parse_note(path, smoke_vault).data
    assert data is not None and data["status"] == "done"
    assert data["protocol"] == "EVAL-v2" and data["dataset"] == "DS-20260801-main-split"
    assert data["metrics"] and all(m["run_id"] and m["as_of"] for m in data["metrics"])
    config = load_config(smoke_vault)
    adapter = get_adapter(config, smoke_vault)
    parent = [r["config"] for r in adapter.fetch(parent_run_ids(Vault.load(smoke_vault), PARENT))]
    child = [r["config"] for r in adapter.fetch(["run-c1", "run-c2"])]
    expected = render_setup(config_diff(PARENT, parent, child, config.hash_ignore))
    text = path.read_text(encoding="utf-8")
    for row in expected.splitlines():
        if row.startswith("| "):
            assert row in text, row


def test_exp_log_refuses_done_without_protocol(claude_bin: str, smoke_vault: Path) -> None:
    folder = smoke_vault / "experiments"
    before = notes_in(folder)
    result = run_skill(claude_bin, smoke_vault, "/lab-brain:exp-log run-noproto")
    for path in notes_in(folder) - before:
        data = parse_note(path, smoke_vault).data
        assert data is None or data.get("status") != "done"
    assert "protocol" in str(result.get("result", "")).lower()
```

Run `uv run ruff format tests/smoke/test_smoke_skills.py`.

If ruff's import sorting moves `from harness import run_skill`, accept ruff's order.

- [ ] **Step 4: Check that the smoke tests are deselected and skip**

Run: `uv run pytest -q`
Expected: the whole suite passes, and the three smoke tests show as deselected.

Run: `uv run pytest -m smoke -v`
Expected: 3 skipped, with reason `claude is not installed` or `set ANTHROPIC_API_KEY …`.

- [ ] **Step 5: Create `scripts/m4-gate.sh`**

```bash
#!/usr/bin/env bash
# M4 gate: install lab-brain from a local marketplace path into a throwaway Claude Code
# config, then run /lab-brain:brief in a copy of the valid fixture vault.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)

checklist() {
  cat <<EOF
M4 gate needs ANTHROPIC_API_KEY and the claude CLI. Manual checklist instead (about 3 minutes):
  1. In Claude Code: /plugin marketplace add $repo
  2. /plugin install lab-brain@lab-brain
  3. Restart Claude Code inside a lab-brain vault.
  4. /lab-brain:brief prints the brief.
  5. /lab-brain:idea test idea creates one note in ideas/inbox/.
  6. Ask "what's the state of this vault?": Claude uses brain-core or brief unprompted.
  7. Ask "write a handoff": the handoff skill runs.
  8. /plugin marketplace remove lab-brain, and delete the test notes.
EOF
}

if [[ -z "${ANTHROPIC_API_KEY:-}" ]] || ! command -v claude >/dev/null 2>&1; then
  checklist
  exit 3
fi

config_dir=$(mktemp -d)
vault_dir=$(mktemp -d)
trap 'rm -rf "$config_dir" "$vault_dir"' EXIT
export CLAUDE_CONFIG_DIR="$config_dir"

claude plugin marketplace add "$repo"
claude plugin install lab-brain@lab-brain
cp -R "$repo/tests/fixtures/valid/." "$vault_dir/"

(cd "$vault_dir" && LABBRAIN_VAULT="$vault_dir" claude -p "/lab-brain:brief" \
  --permission-mode dontAsk --output-format stream-json --verbose) | python3 -c '
import json, sys
events = [json.loads(line) for line in sys.stdin if line.strip()]
init = next(e for e in events if e.get("type") == "system" and e.get("subtype") == "init")
names = [str(p.get("name", "")) for p in init.get("plugins", [])]
assert any(n.startswith("lab-brain") for n in names), f"lab-brain not loaded: {names}"
errors = init.get("plugin_errors", [])
assert not errors, f"plugin errors: {errors}"
result = next(e for e in reversed(events) if e.get("type") == "result")
assert "Open ideas" in str(result.get("result", "")), "the brief did not reach the result"
print("M4 gate passed")
'
```

Then `chmod +x scripts/m4-gate.sh`.

- [ ] **Step 6: Check the gate script here**

Run: `bash -n scripts/m4-gate.sh && (env -u ANTHROPIC_API_KEY scripts/m4-gate.sh; echo "exit $?")`
Expected: no syntax errors, the checklist printed, and `exit 3`.

- [ ] **Step 7: Add the `plugin-validate` job to `.github/workflows/ci.yml`**

Append under `jobs:`:

```yaml
  plugin-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm install -g @anthropic-ai/claude-code
      - name: Require Claude Code 2.1.289 or later
        run: |
          version=$(claude --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
          echo "claude $version"
          printf '%s\n%s\n' 2.1.289 "$version" | sort -V -C || { echo "need claude >= 2.1.289"; exit 1; }
      - run: claude plugin validate . --strict
```

- [ ] **Step 8: Create `.github/workflows/smoke.yml`**

```yaml
name: smoke
on: workflow_dispatch

permissions:
  contents: read

jobs:
  smoke:
    runs-on: ubuntu-latest
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    steps:
      - name: Skip without the secret
        if: env.ANTHROPIC_API_KEY == ''
        run: echo "::notice::ANTHROPIC_API_KEY is not set; smoke tests skipped"
      - if: env.ANTHROPIC_API_KEY != ''
        uses: actions/checkout@v4
      - if: env.ANTHROPIC_API_KEY != ''
        uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.11"
      - if: env.ANTHROPIC_API_KEY != ''
        uses: actions/setup-node@v4
        with:
          node-version: "22"
      - if: env.ANTHROPIC_API_KEY != ''
        run: npm install -g @anthropic-ai/claude-code
      - if: env.ANTHROPIC_API_KEY != ''
        run: uv sync --locked && uv run pytest -m smoke -v
```

- [ ] **Step 9: Full suite and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: all pass, with the smoke tests deselected.

- [ ] **Step 10: Commit**

```bash
git add tests/smoke scripts/m4-gate.sh .github/workflows/ci.yml .github/workflows/smoke.yml pyproject.toml
git commit -m "test: add opt-in skill smoke tests, the M4 gate script and plugin validation in CI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: ADRs, README and CHANGELOG

**Files:**
- Create the four ADRs listed in Step 1, under `docs/decisions/`.
- Modify: `README.md`, `CHANGELOG.md`, `tests/test_adrs.py` (8 → 12)

**Interfaces:**
- Consumes: the decisions made in Tasks 1–9; the existing ADR format, a decision note with a `## For future agents` block (see `docs/decisions/ADR-20261015-frozen-edit-semantics.md`).
- Produces: documentation only.

- [ ] **Step 1: Update the ADR count, and watch it fail**

In `tests/test_adrs.py`, change `assert len(paths) == 8` to `assert len(paths) == 12`.
Run: `uv run pytest tests/test_adrs.py -v`
Expected: FAIL with `assert 8 == 12`.

- [ ] **Step 2: Write the four ADRs**

Use today's date as `YYYYMMDD` in each ID and filename, and as `created` and `updated`. Each file follows the template below. The content of each section follows the template.

```markdown
---
id: ADR-YYYYMMDD-<slug>
type: decision
title: "<title>"
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: claude
status: accepted
tags: [engine, plugin]
links: []
---
## For future agents
<one or two lines>
## Context
<text>
## Decision
<text>
## Alternatives considered
<text>
## Consequences
<text>
```

**`ADR-YYYYMMDD-plugin-layout-and-engine-invocation`**, titled "plugin layout and engine invocation":
- **For future agents:** The plugin is this repo. Skills call `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain`; change the string in every skill and in `tests/test_plugin_manifest.py` together.
- **Context:** The parent spec asks for a single-plugin marketplace in the engine repo. Skills must call an engine of the same version as themselves. `${CLAUDE_PLUGIN_ROOT}` is substituted in SKILL.md text, but is not set in Bash. Plugin `bin/` directories come after the user's PATH and block claude.ai/Cowork installs.
- **Decision:**
  - `.claude-plugin/plugin.json` (version `0.2.0`, kept equal to `pyproject.toml` by a test) and `marketplace.json` with one entry, `source: "./"`, live at the repo root.
  - Skills are in `skills/<name>/SKILL.md`; there is no `commands/` and no `bin/`.
  - Every skill runs the engine as `uvx --from "${CLAUDE_PLUGIN_ROOT}" labbrain`. It pre-approves that string in `allowed-tools`, both quoted and unquoted, because permission rules match the command text.
  - Skills never assign shell variables or use command substitution, because allow rules do not match past an assignment.
  - User text is single-quoted.
  - `[tool.uv] cache-keys` lists `pyproject.toml` and `labbrain/**/*.py`, because without it `uvx --from <checkout>` serves a stale build; this was verified with uv 0.7.17.
- **Alternatives considered:**
  - a `bin/labbrain` shim: it is shadowed by a user's own `labbrain`, and blocks claude.ai/Cowork installs;
  - the vault's pinned uvx command: the engine version would follow the vault, not the skills;
  - prose-only skills: they contradict the spec's rule that deterministic logic lives in Python.
- **Consequences:**
  - The first skill call downloads dependencies from PyPI.
  - Each plugin version builds its own engine.
  - A vault's `CLAUDE.md` keeps its own pinned command for humans and pre-commit, and `engine_min_version` warns when either copy is too old.

**`ADR-YYYYMMDD-local-tracker-adapter`**, titled "local tracker adapter":
- **For future agents:** Run folders are `<runs_dir>/<run_id>/{config.yaml, metrics.json, meta.json}`. Read `labbrain/trackers/local.py` before changing the layout.
- **Context:** `/exp-log` needs runs without a hosted tracker, and protected projects must never let a run path reach individual-level data.
- **Decision:**
  - **Protocol:** `TrackerAdapter` has `fetch` and `run_url`; `search` arrives in M7 with its first user.
  - **Runs directory:** `runs_dir` is relative to `code_repo` when that is set, otherwise to the vault root; an absolute path is used as is.
  - **Protected paths:** relative `data_paths` resolve against the vault root. Every opened path is canonicalised and refused if it lies in a data path, which also covers symlinked runs.
  - **Run IDs** match `[A-Za-z0-9][A-Za-z0-9._-]*`.
  - **Metrics:** only finite numbers are kept.
  - **`meta.json` values** are type-checked, and a bad one is ignored. SHAs are lowercased and must match `[0-9a-f]{7,40}`.
  - **Status:** the meta status, else `finished` with metrics, else `unknown`.
  - **Messages** pass through `sanitize`.
  - **`dataset_key`** (default `data.dataset`) sits beside `protocol_key`.
- **Alternatives considered:**
  - resolving `runs_dir` against the vault only: wrong for standalone vaults beside a code repo;
  - checking only `runs_dir`: a symlinked run would escape;
  - `display_id` for run IDs: it would blank every run ID.
- **Consequences:** The `none` backend and sweeps are deferred to M7, and `wandb`/`mlflow` report "arrives in a later engine version".

**`ADR-YYYYMMDD-exp-record-and-finish`**, titled "exp record and finish":
- **For future agents:** `exp record` decides status, protocol, dataset and code; skills only gather a hypothesis and fill gaps. `finish` is the one end step for every writing skill.
- **Context:** Section 7 of the parent spec says /exp-log must refuse `done` without a protocol. The schema requires a dataset for `done`. Skills must not compute diffs or copy metrics by hand, and a skill's validate, index and log steps used to be three chained commands that permission rules could not approve.
- **Decision:**
  - **Status** from runs: failed > running or unknown > done.
  - **The `done` gate** needs both a protocol and a dataset, each from a flag, a planned note or the runs, and each must exist as a note; disagreement between runs is an error.
  - **`code`:** the runs' shared SHA, else `code sha` on `code_repo`, with the vault excluded from the dirty check; disagreeing SHAs record no code.
  - **Metrics** are stamped with `run_id` and `as_of`. `split` is inferred only from a leading `train`/`val`/`valid`/`validation`/`test` segment.
  - **`--into`** fills only planned or running notes, and appends to Setup and Results.
  - **`finish`** validates, and only when clean runs sync, index and log; `--finish` runs it in the same process.
  - **Note creation is exclusive** (`os.link`) with five ID retries, so parallel handoffs never overwrite each other.
  - **Exit codes** stay 0/1/2, with 2 for every refusal.
- **Alternatives considered:**
  - the skill computing diffs and metrics: not deterministic and not testable;
  - exit 1 for refusals: it would conflict with "1 means findings";
  - `os.replace` for new notes: it silently overwrites a racing writer.
- **Consequences:** A finished run group without a dataset note cannot be logged as `done` until one exists. `--planned` notes record no code until `exp record --into`.

**`ADR-YYYYMMDD-skill-smoke-tests`**, titled "skill smoke tests":
- **For future agents:** `uv run pytest -m smoke` needs `claude`, plus `ANTHROPIC_API_KEY` or `LABBRAIN_SMOKE_LOGIN=1`. Record new findings about permission behaviour here.
- **Context:** The M4 gate needs headless `/idea` and `/exp-log` runs, and real model calls cost money and need credentials.
- **Decision:**
  - **Marker:** smoke tests carry the `smoke` marker, are deselected by default, and skip without `claude` or credentials.
  - **Default isolation:** `claude --bare -p "/lab-brain:<skill> …" --plugin-dir <repo> --permission-mode dontAsk --allowedTools Read Edit Write --max-turns 15 --max-budget-usd 1`.
  - **`LABBRAIN_SMOKE_LOGIN=1`:** runs without `--bare`, using the user's login and only project settings.
  - **`LABBRAIN_SMOKE_ALLOW_ENGINE=1`:** also pre-approves the engine command, in case a skill's own `allowed-tools` is not honoured under `dontAsk`. The docs do not say whether it is; record the first real run's outcome here.
  - **CI:** `smoke.yml` runs only on manual dispatch and only with the secret. `ci.yml` runs `claude plugin validate . --strict`, which needs no key, on Claude Code 2.1.289 or later.
  - **Gate:** `scripts/m4-gate.sh` installs from a local marketplace path into a temporary `CLAUDE_CONFIG_DIR`, or prints a manual checklist and exits 3.
- **Alternatives considered:** a smoke job on every PR (cost per push); recorded transcripts (they would not exercise the real skill loader).
- **Consequences:** Automatic skill invocation (`brain-core`, `handoff`) is checked only by the manual checklist, because bare mode sends no skill listing.

- [ ] **Step 3: Update `README.md`**

Insert after the intro paragraph, before `## Commands`:

```markdown
## Using the plugin

This repository is also a Claude Code plugin. In Claude Code:

    /plugin marketplace add jorgebotas/lab-brain
    /plugin install lab-brain@lab-brain

Skills (run inside a vault):

- `/lab-brain:idea <text>`: capture an idea in `ideas/inbox/`
- `/lab-brain:exp-log <run-id...> [--parent EXP-ID] [--planned]`: log runs as an experiment
- `/lab-brain:decide <summary>`: record a decision
- `/lab-brain:handoff`: write the session handoff
- `/lab-brain:brief`: where the project stands

`brain-core` loads on its own in any vault. The skills run the engine bundled with the
plugin through `uvx`, so `uv` must be installed. Update with
`claude plugin update lab-brain@lab-brain`.
```

Add to the `## Commands` block:

```
    labbrain new idea --title "Cosine warmup" --author claude --summary "..." --finish "idea: Cosine warmup"
    labbrain finish ideas/inbox/IDEA-20261015-cosine-warmup.md --log "idea: Cosine warmup"
    labbrain tracker fetch run-1 run-2  # local runs as JSON
    labbrain tracker diff run-2 --parent EXP-20261001-baseline
    labbrain exp record run-2 --title "Lower LR" --author claude --protocol EVAL-v2 --dataset DS-20260801-main
    labbrain code sha                   # code repo commit and dirty flag
    labbrain brief                      # recent handoffs, open work, lint counts
```

Add to `## Development`:

```
    uv run pytest -m smoke              # headless skill runs; needs claude and ANTHROPIC_API_KEY
                                        # (or LABBRAIN_SMOKE_LOGIN=1 to use your login)
    scripts/m4-gate.sh                  # install from a local marketplace and run /lab-brain:brief
```

- [ ] **Step 4: Update `CHANGELOG.md`**

Insert above `## 0.1.0 (2026-10-16)`. The date is filled in on release day; until then, write `## 0.2.0 (unreleased)`.

```markdown
## 0.2.0 (unreleased)

### Added

- Claude Code plugin: `.claude-plugin/plugin.json`, a single-plugin `marketplace.json`, and
  six skills (`brain-core`, `idea`, `exp-log`, `decide`, `handoff`, `brief`) that run the
  bundled engine through `uvx`.
- `labbrain tracker fetch` and `tracker diff`, with a `local` adapter that refuses any run
  path inside `data_paths`.
- `labbrain exp record`: experiment notes from runs, with stamped headline metrics, a config
  diff against a parent, and a gate requiring a protocol and a dataset for finished runs.
- `labbrain finish` and `--finish` on `new` and `exp record`: validate, then sync, index and
  log in one step.
- `labbrain code sha`, `labbrain brief` (and `--short`), and `--summary`, `--body`, `--tag`
  and `--status` on `new`.
- `dataset_key` config option (default `data.dataset`).
- Opt-in headless smoke tests (`pytest -m smoke`), `scripts/m4-gate.sh`, and
  `claude plugin validate` in CI.

### Changed

- New notes are created exclusively, so two writers can never overwrite each other's note.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_adrs.py tests/test_meta.py -v`
Expected: PASS. `test_meta` scans `README.md`, `CHANGELOG.md` and the ADRs. If it flags a line, reword it.

- [ ] **Step 6: Full suite and linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest --cov --cov-fail-under=85`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add docs/decisions README.md CHANGELOG.md tests/test_adrs.py
git commit -m "docs: add M4 ADRs, plugin usage and the 0.2.0 changelog

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the plan: release (needs the user's approval at each step)

1. Push `feat/m4-plugin`, then open a PR to `main` with the gate status: unit, coverage and plugin-validate in CI; smoke and gate as run or as pending on the user's side.
2. The user runs either the smoke tests (`ANTHROPIC_API_KEY=… uv run pytest -m smoke`, or `LABBRAIN_SMOKE_LOGIN=1 uv run pytest -m smoke`) or `scripts/m4-gate.sh`, or the manual checklist. Record the `dontAsk` + `allowed-tools` outcome in the smoke ADR.
3. On green CI and with the user's approval: replace `(unreleased)` with the date, merge, and tag `v0.2.0`.
4. Then write the template v0.2.0 plan (spec section 10) in `jorgebotas/lab-brain-template`.
