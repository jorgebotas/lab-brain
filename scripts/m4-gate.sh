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

config_dir=""
vault_dir=""
cleanup() {
  if [[ -n "$config_dir" ]]; then rm -rf "$config_dir"; fi
  if [[ -n "$vault_dir" ]]; then rm -rf "$vault_dir"; fi
}
trap cleanup EXIT
config_dir=$(mktemp -d)
vault_dir=$(mktemp -d)
export CLAUDE_CONFIG_DIR="$config_dir"

claude plugin marketplace add "$repo"
claude plugin install lab-brain@lab-brain
cp -R "$repo/tests/fixtures/valid/." "$vault_dir/"

# The checker uses explicit sys.exit checks, not assert, so python -O cannot strip them.
(cd "$vault_dir" && LABBRAIN_VAULT="$vault_dir" claude -p "/lab-brain:brief" \
  --permission-mode dontAsk --output-format stream-json --verbose) | python3 -c '
import json, sys

events = []
for number, line in enumerate(sys.stdin, 1):
    if line.strip():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            sys.exit(f"M4 gate failed: line {number} of the stream-json output is not JSON")
inits = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
if not inits:
    sys.exit("M4 gate failed: no system init event in the output")
names = [str(p.get("name", "")) for p in inits[0].get("plugins") or []]
if not any(n.startswith("lab-brain") for n in names):
    sys.exit(f"M4 gate failed: lab-brain is not loaded; plugins: {names}")
errors = inits[0].get("plugin_errors") or []
if errors:
    sys.exit(f"M4 gate failed: plugin errors: {errors}")
results = [e for e in events if e.get("type") == "result"]
if not results:
    sys.exit("M4 gate failed: no result event in the output")
result = results[-1]
subtype = result.get("subtype")
if result.get("is_error"):
    sys.exit(f"M4 gate failed: the run ended in an error (subtype {subtype!r})")
denials = result.get("permission_denials") or []
if denials:
    sys.exit(
        f"M4 gate failed: permission denied for {denials}; the skill allowed-tools were not"
        " honoured under dontAsk. Pre-approve the engine with --allowedTools and record the"
        " outcome in the smoke-test ADR"
    )
if "Open ideas" not in str(result.get("result", "")):
    sys.exit("M4 gate failed: the brief did not reach the result")
print("M4 gate passed")
'
