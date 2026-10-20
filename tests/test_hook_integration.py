"""M5 integration: every corpus row and file-tool case through the hook entry point.

The Bash corpus (`CASES`, `GITIGNORED_CASES`) and its world come from `test_hook_bash`
(ruling R4). Each world is built once per module and every row is replayed as a recorded
payload through `run_hook`, so the leak and no-allow checks see every output at once. The
latency budget runs the real CLI in a subprocess, and the `hooks.json` commands are run
through `sh -c` to show they fail closed when the engine cannot start.
"""

from __future__ import annotations

import json
import secrets
import statistics
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from helpers import clean_env, hook_payload
from test_hook_bash import CASES, GITIGNORED_CASES, BashWorld, make_bash_world

from labbrain.hooks.entry import run_hook

REPO = Path(__file__).resolve().parents[1]
HOOKS_JSON = REPO / "hooks" / "hooks.json"

# (case_id, tool_name, tool_input template, expected). Placeholders as in the Bash corpus,
# plus {repo}, {vault}, {home} and {name} (a data file whose name is a sentinel).
FILE_CASES: list[tuple[str, str, dict[str, Any], str]] = [
    ("read-root-file", "Read", {"file_path": "{R}/rows.csv"}, "deny"),
    ("read-root", "Read", {"file_path": "{R}"}, "deny"),
    ("read-case", "Read", {"file_path": "{R_upper}/rows.csv"}, "deny"),
    ("read-link", "Read", {"file_path": "{repo}/data/rows.csv"}, "deny"),
    ("read-relative-link", "Read", {"file_path": "data/rows.csv"}, "deny"),
    ("read-dotdot", "Read", {"file_path": "{repo}/../mnt/phi/rows.csv"}, "deny"),
    ("read-home-link", "Read", {"file_path": "{home}/phi/rows.csv"}, "deny"),
    ("read-spaced-root", "Read", {"file_path": "{tmp}/mnt/phi data/f.csv"}, "deny"),
    ("read-sentinel-name", "Read", {"file_path": "{R}/{name}.csv"}, "deny"),
    ("read-readme", "Read", {"file_path": "{repo}/README.md"}, "allow"),
    ("read-guard-config", "Read", {"file_path": "{vault}/.labbrain/config.yaml"}, "allow"),
    ("write-root", "Write", {"file_path": "{R}/new.csv", "content": "x\n"}, "deny"),
    ("write-link", "Write", {"file_path": "{repo}/data/new.csv", "content": "x\n"}, "deny"),
    ("write-repo", "Write", {"file_path": "{repo}/out.txt", "content": "x\n"}, "allow"),
    ("write-note", "Write", {"file_path": "{vault}/notes/n.md", "content": "A note.\n"}, "allow"),
    (
        "write-guard-config",
        "Write",
        {"file_path": "{vault}/.labbrain/config.yaml", "content": "protected_data: false\n"},
        "deny",
    ),
    (
        "write-settings",
        "Write",
        {"file_path": "{repo}/.claude/settings.json", "content": "{{}}\n"},
        "deny",
    ),
    (
        "write-plugin-root",
        "Write",
        {"file_path": "{plugin_root}/labbrain/hooks/guard.py", "content": "\n"},
        "deny",
    ),
    (
        "edit-root",
        "Edit",
        {"file_path": "{R}/rows.csv", "old_string": "id", "new_string": "x"},
        "deny",
    ),
    (
        "edit-link",
        "Edit",
        {"file_path": "{repo}/data/rows.csv", "old_string": "a", "new_string": "b"},
        "deny",
    ),
    (
        "edit-readme",
        "Edit",
        {"file_path": "{repo}/README.md", "old_string": "# repo", "new_string": "# Repo"},
        "allow",
    ),
    (
        "edit-guard-config",
        "Edit",
        {"file_path": "{vault}/.labbrain/config.yaml", "old_string": "Toy", "new_string": "X"},
        "deny",
    ),
]

# Bash rows that name the sentinel file, or reach it by recursion; all deny.
SENTINEL_BASH = [
    "cat {R}/{name}.csv",
    "head -1 {tmp}/mnt/phi/{name}.csv",
    "ls {R}",
    "grep -r x {tmp}/mnt",
    "find {tmp}/mnt -name '*.csv'",
]
# Search tools over the data root or an ancestor of it; all deny.
SENTINEL_TOOLS: list[tuple[str, dict[str, Any]]] = [
    ("Glob", {"pattern": "**/*.csv", "path": "{tmp}/mnt"}),
    ("Glob", {"pattern": "{R}/*.csv"}),
    ("Grep", {"pattern": "x", "path": "{tmp}/mnt"}),
    ("Grep", {"pattern": "x", "path": "{R}"}),
]


@dataclass
class Run:
    """One hook call: what was sent and what came back."""

    label: str
    event: str
    expected: str  # "deny", "allow" or "" (not a decision: session-start, post-tool-use)
    text: str  # the command or rendered tool_input, for the command-echo check
    code: int
    out: str
    err: str


@dataclass
class Corpus:
    worlds: list[BashWorld]
    sentinels: list[str]
    runs: list[Run]


def _render(w: BashWorld, extra: dict[str, str], value: Any) -> Any:
    if isinstance(value, str):
        for key, text in extra.items():
            value = value.replace("{" + key + "}", text)
        return w.render(value)
    if isinstance(value, dict):
        return {k: _render(w, extra, v) for k, v in value.items()}
    return value


def _extra(w: BashWorld, name: str) -> dict[str, str]:
    return {"repo": str(w.repo), "vault": str(w.vault), "home": str(w.home), "name": name}


def _tool_payload(w: BashWorld, tool_name: str, tool_input: dict[str, Any]) -> bytes:
    fixture = {"Write": "write", "Edit": "edit"}.get(tool_name, "read")
    if tool_name == "Edit":
        tool_input = {"replace_all": False, **tool_input}
    return hook_payload(fixture, cwd=w.cwd, tool_name=tool_name, tool_input=tool_input)


def _bash_payload(w: BashWorld, command: str) -> bytes:
    return hook_payload(
        "bash", cwd=w.cwd, tool_input={"command": command, "description": "Run a command"}
    )


def _call(label: str, event: str, expected: str, text: str, data: bytes, w: BashWorld) -> Run:
    code, out, err = run_hook(event, data, w.env)
    return Run(label, event, expected, text, code, out, err)


def _plant_name_sentinel(w: BashWorld) -> str:
    """A data file whose name is a sentinel, in each protected root of the world."""
    name = secrets.token_hex(16)
    for configured in w.data_paths:
        (Path(configured) / f"{name}.csv").write_text(f"{w.sentinel}\n")
    return name


def _replay(w: BashWorld, cases: list[tuple[str, str, str]], name: str) -> Iterator[Run]:
    for case_id, command, expected in cases:
        rendered = w.render(command)
        yield _call(
            f"bash:{case_id}", "pre-tool-use", expected, rendered, _bash_payload(w, rendered), w
        )
    for command in SENTINEL_BASH:
        rendered = _render(w, _extra(w, name), command)
        yield _call(
            "bash:sentinel", "pre-tool-use", "deny", rendered, _bash_payload(w, rendered), w
        )
    for tool_name, template in SENTINEL_TOOLS:
        tool_input = _render(w, _extra(w, name), template)
        data = _tool_payload(w, tool_name, tool_input)
        yield _call(
            f"{tool_name}:sentinel", "pre-tool-use", "deny", json.dumps(tool_input), data, w
        )


def _replay_files(w: BashWorld, name: str) -> Iterator[Run]:
    for case_id, tool_name, template, expected in FILE_CASES:
        tool_input = _render(w, _extra(w, name), template)
        data = _tool_payload(w, tool_name, tool_input)
        yield _call(f"{tool_name}:{case_id}", "pre-tool-use", expected, "", data, w)


def _replay_other_events(w: BashWorld) -> Iterator[Run]:
    for source in ("startup", "resume", "clear", "compact"):
        data = hook_payload("session_start", cwd=w.cwd, source=source)
        yield _call(f"session-start:{source}", "session-start", "", "", data, w)
    note = w.vault / "notes" / "n.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("A note.\n")
    data = hook_payload("post_write", cwd=w.cwd, path=note, content="A note.")
    yield _call("post-tool-use:write", "post-tool-use", "", "", data, w)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Corpus]:
    """Both Bash worlds, with every row, file case and other event replayed once."""
    worlds: list[BashWorld] = []
    sentinels: list[str] = []
    runs: list[Run] = []
    with pytest.MonkeyPatch.context() as monkeypatch:
        for gitignored, cases in ((False, CASES), (True, GITIGNORED_CASES)):
            w = make_bash_world(
                tmp_path_factory.mktemp("gitignored" if gitignored else "world"),
                monkeypatch,
                gitignored=gitignored,
            )
            name = _plant_name_sentinel(w)
            worlds.append(w)
            sentinels += [w.sentinel, name]
            runs += _replay(w, cases, name)
            if not gitignored:
                runs += _replay_files(w, name)
            runs += _replay_other_events(w)
        yield Corpus(worlds, sentinels, runs)


def test_corpus_through_entry(corpus: Corpus) -> None:
    """Every deny row exits 2 with a reason; every allow row exits 0 silently."""
    decided = [r for r in corpus.runs if r.expected]
    assert len(decided) >= len(CASES) + len(GITIGNORED_CASES) + len(FILE_CASES)
    wrong = [
        (r.label, r.code)
        for r in decided
        if r.code != {"deny": 2, "allow": 0}[r.expected]
        or (r.expected == "deny" and not r.err.strip())
        or (r.expected == "allow" and (r.out or r.err))
    ]
    assert wrong == [], wrong


def test_other_events_exit_cleanly(corpus: Corpus) -> None:
    others = [r for r in corpus.runs if not r.expected]
    assert others and all(r.code == 0 for r in others), [(r.label, r.code, r.err) for r in others]
    assert all(r.out.strip() for r in others if r.event == "session-start")


def test_no_output_ever_has_permission_decision(corpus: Corpus) -> None:
    for r in corpus.runs:
        assert r.code in (0, 2), r.label
        if r.event != "session-start":
            assert r.out == "", r.label
            continue
        assert "permissionDecision" not in r.out, r.label
        try:
            parsed = json.loads(r.out)
        except ValueError:
            continue  # plain text, as required
        assert not isinstance(parsed, (dict, list)), r.label


def test_sentinels_never_in_any_output(corpus: Corpus) -> None:
    everything = "".join(r.out + r.err for r in corpus.runs)
    assert len(corpus.sentinels) == 4
    for sentinel in corpus.sentinels:
        assert sentinel not in everything
    for w in corpus.worlds:
        assert "rows.csv" not in everything and str(w.root / "rows.csv") not in everything
    # Nor the command or tool input: checked for long texts, so a fixed message that happens
    # to contain a two-word command like `rg x` cannot fail the test.
    for r in corpus.runs:
        if len(r.text) >= 16:
            assert r.text not in r.out + r.err, r.label
    assert "Traceback" not in everything


# --- latency -------------------------------------------------------------------------------


def _median_cli_seconds(data: bytes, cwd: Path, env: dict[str, str], expected: int) -> float:
    """Median wall time of `python -m labbrain hook pre-tool-use`: one warm-up, then 5 runs."""
    times: list[float] = []
    for attempt in range(6):
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-m", "labbrain", "hook", "pre-tool-use"],
            input=data,
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=60,
        )
        elapsed = time.perf_counter() - start
        assert proc.returncode == expected, proc.stderr.decode(errors="replace")
        if attempt:
            times.append(elapsed)
    return statistics.median(times)


@pytest.mark.slow
def test_warm_latency_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("x\n")
    no_vault_env = clean_env(HOME=str(tmp_path))
    read = hook_payload("read", cwd=outside, path=outside / "f.txt")
    no_vault = _median_cli_seconds(read, outside, no_vault_env, 0)
    assert no_vault <= 0.45, f"no vault: {no_vault:.3f}s median"

    w = make_bash_world(tmp_path / "world", monkeypatch)
    env = {**clean_env(), **w.env}
    read = hook_payload("read", cwd=w.cwd, path=w.repo / "README.md")
    protected_read = _median_cli_seconds(read, w.cwd, env, 0)
    assert protected_read <= 0.9, f"protected Read: {protected_read:.3f}s median"

    status = _bash_payload(w, "git status")
    protected_bash = _median_cli_seconds(status, w.cwd, env, 0)
    assert protected_bash <= 0.9, f"protected Bash git status: {protected_bash:.3f}s median"


# --- hooks.json fails closed -----------------------------------------------------------------


def _commands(event: str) -> list[str]:
    config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    return [hook["command"] for group in config["hooks"][event] for hook in group["hooks"]]


@pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse"])
def test_hooks_json_commands_fail_closed(tmp_path: Path, event: str) -> None:
    """With the engine unreachable (no uvx on PATH, no plugin root), the call is blocked."""
    commands = _commands(event)
    assert commands
    data = hook_payload("read", cwd=tmp_path, path=tmp_path / "f.txt")
    env = {"CLAUDE_PLUGIN_ROOT": "/nonexistent", "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    for command in commands:
        proc = subprocess.run(
            ["sh", "-c", command],
            input=data,
            cwd=tmp_path,
            env=env,
            capture_output=True,
            timeout=60,
        )
        assert proc.returncode == 2, (command, proc.returncode)
