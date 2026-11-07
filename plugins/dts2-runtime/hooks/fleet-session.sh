#!/usr/bin/env bash
# SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd: keep this session's fleet registry entry fresh and pick up broadcasts. Never fails a session.
# Usage: fleet-session.sh <event>
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${CLAUDE_PLUGIN_ROOT}/hooks/lib-settings.sh"
FLEET_TIMEOUT_SECONDS=5
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting fleet true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
event="${1:-}"
[[ -n "$event" ]] || exit 0
HOOK_INPUT=""
[[ -t 0 ]] || read -r -t 1 -d '' HOOK_INPUT || true
[[ -n "$HOOK_INPUT" ]] || exit 0
# $PPID is the Claude process; the python child's own parent would be `timeout`, so it is passed in.
printf '%s' "$HOOK_INPUT" | timeout "$FLEET_TIMEOUT_SECONDS" python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/fleet.py" hook --event "$event" --pid "$PPID" 2>/dev/null
exit 0
