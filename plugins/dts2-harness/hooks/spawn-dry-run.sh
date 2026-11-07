#!/usr/bin/env bash
# PreToolUse (Bash `lanes.py spawn ... --dry-run`, and Agent when `spawn_dry_run: true`): print the composed brief and the exact
# son command, then refuse the call so nothing starts. Cheap by default: only a payload naming --dry-run (or an Agent call with
# the setting on) reaches python. Never fails a real dispatch.
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${CLAUDE_PLUGIN_ROOT}/hooks/lib-settings.sh"
[[ "$(setting enabled true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
payload="$(cat)"
agent_flag=""
[[ "$(setting spawn_dry_run false)" == "true" ]] && agent_flag="--agent-dry-run"
[[ "$payload" == *--dry-run* || -n "$agent_flag" ]] || exit 0
if [[ -n "$agent_flag" ]]; then
  printf '%s' "$payload" | python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/spawn_dry_run.py" --agent-dry-run
else
  printf '%s' "$payload" | python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/spawn_dry_run.py"
fi
exit 0
