"""Headless end-to-end gate for the hooks (M5): data reads and frozen-note rewrites are blocked.

Each run is `claude -p … --plugin-dir <repo>` in a protected vault, without `--bare`,
because bare mode skips plugin hooks. Only project settings are loaded, so the user's own
hooks and plugins stay out. The data folder is added with `--add-dir` and the tools are
pre-approved, so a block can only come from the lab-brain hooks, never from a permission rule.
The stream-json output and the session transcript are both checked for the sentinel.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from harness import REPO
from helpers import commit_all, copy_fixture, git, make_vault

pytestmark = pytest.mark.smoke
DATA_GUARD = "lab-brain data guard"
FROZEN_GUARD = "lab-brain frozen-file guard"
EXPERIMENT = "experiments/EXP-20260910-label-smoothing.md"


@dataclass
class HookVault:
    vault: Path
    phi: Path
    rows: Path
    sentinel: str


@dataclass
class Session:
    events: list[dict[str, Any]]
    stdout: str
    transcript: str

    def tool_uses(self) -> list[dict[str, Any]]:
        return [
            block
            for e in self.events
            if e.get("type") == "assistant"
            for block in (e.get("message") or {}).get("content") or []
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]

    def tool_result(self, tool_use_id: str) -> str:
        for e in self.events:
            if e.get("type") != "user":
                continue
            for block in (e.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("tool_use_id") == tool_use_id:
                    return json.dumps(block)
        return ""

    def result_text(self) -> str:
        results = [e for e in self.events if e.get("type") == "result"]
        assert results, "no result event in the output"
        return str(results[-1].get("result", ""))


@pytest.fixture
def hook_vault(tmp_path: Path) -> HookVault:
    """The valid fixture as a protected vault whose one data path is `<tmp>/phi`."""
    tmp = tmp_path.resolve()
    sentinel = secrets.token_hex(16)
    phi = tmp / "phi"
    phi.mkdir()
    rows = phi / "rows.csv"
    rows.write_text(f"id,value\n{sentinel},1\n", encoding="utf-8")
    vault = copy_fixture(tmp / "vault")
    config = (vault / ".labbrain" / "config.yaml").read_text(encoding="utf-8")
    assert "protected_data: true" in config and "data_paths: []" in config
    make_vault(vault, config.replace("data_paths: []", f"data_paths: ['{phi}']"))
    git(vault, "init", "-q", "-b", "main")
    commit_all(vault, "smoke vault")
    return HookVault(vault, phi, rows, sentinel)


def _transcript(session_id: str) -> str:
    homes = [Path(os.environ["CLAUDE_CONFIG_DIR"])] if os.environ.get("CLAUDE_CONFIG_DIR") else []
    homes.append(Path.home() / ".claude")
    for home in homes:
        for path in (home / "projects").glob(f"*/{session_id}.jsonl"):
            return path.read_text(encoding="utf-8", errors="replace")
    pytest.fail(f"no transcript for session {session_id} under {homes}", pytrace=False)


def run_session(claude: str, hv: HookVault, prompt: str, allowed: list[str]) -> Session:
    cmd = [
        claude,
        "-p",
        prompt,
        "--plugin-dir",
        str(REPO),
        "--setting-sources",
        "project",
        "--add-dir",
        str(hv.phi),
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        *allowed,
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        "10",
        "--max-budget-usd",
        "1",
    ]
    # uv 0.7-0.10 may serve a stale `uvx --from <checkout>` build despite cache-keys; rebuild.
    env = {**os.environ, "LABBRAIN_VAULT": str(hv.vault), "UV_NO_CACHE": "1"}
    env.pop("LABBRAIN_NOW", None)
    proc = subprocess.run(
        cmd,
        cwd=hv.vault,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, (
        f"claude exited {proc.returncode}\nstderr:\n{proc.stderr[-4000:]}"
        f"\nstdout:\n{proc.stdout[-2000:]}"
    )
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    inits = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    assert inits, "no system init event in the output"
    names = [str(p.get("name", "")) for p in inits[0].get("plugins") or []]
    assert any(n.startswith("lab-brain") for n in names), f"lab-brain not loaded: {names}"
    assert not inits[0].get("plugin_errors"), inits[0].get("plugin_errors")
    transcript = _transcript(str(inits[0].get("session_id", "")))
    return Session(events, proc.stdout, transcript)


def test_read_of_data_blocked(claude_bin: str, hook_vault: HookVault) -> None:
    rows = hook_vault.rows
    prompt = (
        f"Show me the contents of {rows}. First use the Read tool on that file. Then, whatever "
        f"happened, run `cat {rows}` with the Bash tool. Report what each attempt returned."
    )
    session = run_session(claude_bin, hook_vault, prompt, ["Read", "Bash(cat *)"])
    assert hook_vault.sentinel not in session.result_text()
    assert hook_vault.sentinel not in session.stdout
    assert hook_vault.sentinel not in session.transcript
    touching = [u for u in session.tool_uses() if str(hook_vault.phi) in json.dumps(u["input"])]
    assert {u["name"] for u in touching} >= {"Read", "Bash"}, [u["name"] for u in touching]
    for use in touching:
        assert DATA_GUARD in session.tool_result(use["id"]), use["name"]
    assert DATA_GUARD in session.transcript


def test_frozen_body_edit_blocked(claude_bin: str, hook_vault: HookVault) -> None:
    path = hook_vault.vault / EXPERIMENT
    before = path.read_bytes()
    prompt = (
        f"Rewrite the body of {EXPERIMENT}: replace all the text under its '## Results' heading "
        "with the single line 'Results withdrawn.'. Use the Edit tool, not Bash. If the edit "
        "is blocked, stop and report the message."
    )
    session = run_session(claude_bin, hook_vault, prompt, ["Read", "Edit", "Write"])
    assert path.read_bytes() == before
    edits = [
        u
        for u in session.tool_uses()
        if u["name"] in ("Edit", "Write", "MultiEdit") and EXPERIMENT in json.dumps(u["input"])
    ]
    assert edits, [u["name"] for u in session.tool_uses()]
    for use in edits:
        assert FROZEN_GUARD in session.tool_result(use["id"]), use["name"]
