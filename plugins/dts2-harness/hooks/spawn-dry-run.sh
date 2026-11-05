#!/usr/bin/env bash
# PreToolUse (Bash `lanes.py spawn ... --dry-run`, and Agent when `spawn_dry_run: true`): print the composed brief and the exact
# son command, then refuse the call so nothing starts. Cheap by default: only a payload naming --dry-run (or an Agent call with
# the setting on) reaches python. Never fails a real dispatch.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ "$(setting enabled true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
payload="$(cat)"
agent_flag=""
[[ "$(setting spawn_dry_run false)" == "true" ]] && agent_flag="--agent-dry-run"
[[ "$payload" == *--dry-run* || -n "$agent_flag" ]] || exit 0
# shellcheck disable=SC2086 # the flag is empty or one word
printf '%s' "$payload" | python3 -I "$PLUGIN_DIR/scripts/spawn_dry_run.py" $agent_flag
exit 0
