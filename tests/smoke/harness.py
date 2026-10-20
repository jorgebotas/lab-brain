"""Headless skill runs for the smoke tests (`uv run pytest -m smoke`).

By default each run is `claude --bare -p "/lab-brain:<skill> …" --plugin-dir <repo>`,
which needs ANTHROPIC_API_KEY. LABBRAIN_SMOKE_LOGIN=1 runs without --bare using your
normal login, with only project settings loaded. LABBRAIN_SMOKE_ALLOW_ENGINE=1 also
pre-approves the engine command, for when a skill's own allowed-tools is not honoured
under --permission-mode dontAsk. LABBRAIN_SMOKE_REQUIRED=1 turns the missing-claude or
missing-credentials skips into failures (the smoke workflow sets it).

A run fails on a non-zero exit, on `is_error` in the JSON result, and on any permission
denial, so a skill whose engine calls were blocked cannot pass silently.
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
        "-p",
        prompt,
        "--plugin-dir",
        str(REPO),
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        *allowed,
        "--output-format",
        "json",
        "--max-turns",
        "15",
        "--max-budget-usd",
        "1",
    ]
    if LOGIN:
        cmd += ["--setting-sources", "project"]
    # uv 0.7-0.10 may serve a stale `uvx --from <checkout>` build despite cache-keys; rebuild.
    env = {**os.environ, "LABBRAIN_VAULT": str(vault), "UV_NO_CACHE": "1"}
    env.pop("LABBRAIN_NOW", None)
    proc = subprocess.run(
        cmd,
        cwd=vault,
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
    result: dict[str, Any] = json.loads(proc.stdout)
    assert not result.get("is_error"), (
        f"claude reported an error (subtype {result.get('subtype')!r}): "
        f"{str(result.get('result', ''))[-2000:]}"
    )
    denials = result.get("permission_denials") or []
    assert not denials, (
        f"permission denied: {'; '.join(describe_denial(d) for d in denials)}. "
        "Set LABBRAIN_SMOKE_ALLOW_ENGINE=1 to pre-approve the engine and record the outcome "
        "in the smoke-test ADR"
    )
    return result


def describe_denial(denial: Any) -> str:
    """One compact line per denial entry: the tool name plus its command, whatever the keys."""
    if not isinstance(denial, dict):
        return str(denial)[:300]
    name = denial.get("tool_name") or denial.get("tool") or denial.get("name") or "?"
    tool_input = denial.get("tool_input") or denial.get("input")
    if isinstance(tool_input, dict) and "command" in tool_input:
        detail = str(tool_input["command"])
    elif tool_input is not None:
        detail = json.dumps(tool_input, default=str)
    else:
        rest = {k: v for k, v in denial.items() if k not in {"tool_name", "tool", "name"}}
        detail = json.dumps(rest, default=str)
    return f"{name}({detail[:300]})"
