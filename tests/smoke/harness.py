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
    env = {**os.environ, "LABBRAIN_VAULT": str(vault)}
    env.pop("LABBRAIN_NOW", None)
    proc = subprocess.run(cmd, cwd=vault, env=env, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout)
