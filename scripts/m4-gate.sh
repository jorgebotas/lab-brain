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
