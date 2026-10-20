#!/usr/bin/env bash
# M5 gate: run the hooks smoke tests, where a headless claude -p session loads the plugin
# from this checkout in a protected vault and tries to read a data file and rewrite a frozen
# note. Needs the claude CLI plus ANTHROPIC_API_KEY, or LABBRAIN_SMOKE_LOGIN=1 for your login.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)

checklist() {
  cat <<EOF
M5 gate needs the claude CLI plus ANTHROPIC_API_KEY (or LABBRAIN_SMOKE_LOGIN=1).
Manual checklist instead (about 5 minutes):
  1. Make a vault with protected_data: true and a data_paths entry for a folder holding
     rows.csv with a made-up marker value. git init and commit it.
  2. Start Claude Code in it with: claude --plugin-dir $repo
  3. Ask it to show rows.csv with the Read tool, then with cat. Both calls are blocked
     with "lab-brain data guard", and the marker never appears.
  4. Ask it to rewrite the body of a committed done experiment. The edit is blocked with
     "lab-brain frozen-file guard", and git diff shows no change.
  5. Delete the test vault.
EOF
}

if ! command -v claude >/dev/null 2>&1 \
  || { [[ -z "${ANTHROPIC_API_KEY:-}" ]] && [[ "${LABBRAIN_SMOKE_LOGIN:-}" != "1" ]]; }; then
  checklist
  exit 3
fi

# uv 0.7-0.10 may serve a stale `uvx --from <checkout>` build despite cache-keys; rebuild.
export UV_NO_CACHE=1
# A missing claude or missing credentials must fail the gate, not skip it.
export LABBRAIN_SMOKE_REQUIRED=1
cd "$repo"
uv run pytest -m smoke -v tests/smoke/test_smoke_hooks.py
echo "M5 gate passed"
