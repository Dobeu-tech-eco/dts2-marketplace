#!/usr/bin/env bash
# PostToolUse (all tools): stop a run on a context spike before the plan checkpoint, or when started in a member repo. Never fails the session.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
TOOL_CALLS_DEFAULT=250
MB_DEFAULT=12
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting context_guard true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
number_or() {
  if [[ "$1" =~ ^[0-9]+$ ]]; then
    echo "$1"
  else
    echo "$2"
  fi
}
TOOL_LIMIT="$(number_or "$(setting context_guard_tool_calls "$TOOL_CALLS_DEFAULT")" "$TOOL_CALLS_DEFAULT")"
MB_LIMIT="$(number_or "$(setting context_guard_mb "$MB_DEFAULT")" "$MB_DEFAULT")"
STOP_FLAG=()
[[ "$(setting context_guard_stop false)" == "true" ]] && STOP_FLAG=(--stop)
exec python3 -I "$PLUGIN_DIR/scripts/context-guard.py" --tool-calls "$TOOL_LIMIT" --mb "$MB_LIMIT" ${STOP_FLAG[@]+"${STOP_FLAG[@]}"}
