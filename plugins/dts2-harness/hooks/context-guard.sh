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
number_or() { [[ "$1" =~ ^[0-9]+$ ]] && echo "$1" || echo "$2"; }
TOOL_LIMIT="$(number_or "$(setting context_guard_tool_calls "$TOOL_CALLS_DEFAULT")" "$TOOL_CALLS_DEFAULT")"
MB_LIMIT="$(number_or "$(setting context_guard_mb "$MB_DEFAULT")" "$MB_DEFAULT")"
STOP_FLAG=()
[[ "$(setting context_guard_stop false)" == "true" ]] && STOP_FLAG=(--stop)
payload="$(cat)"
guard_out="$(printf '%s' "$payload" | python3 -I "$PLUGIN_DIR/scripts/context-guard.py" --tool-calls "$TOOL_LIMIT" --mb "$MB_LIMIT" ${STOP_FLAG[@]+"${STOP_FLAG[@]}"})"
[[ -n "$guard_out" ]] && printf '%s\n' "$guard_out"
# Inside a son (branch prefix dts2/<stamp>/lane-<lane>) a fired guard parks the lane through the mailbox, never by writing phase files.
if [[ -n "$guard_out" && "${DTS2_SON_BRANCH_PREFIX:-}" =~ ^dts2/([^/]+)/lane-(.+)$ ]]; then
  SESSION_FLAG=()
  [[ -n "${CLAUDE_CODE_SESSION_ID:-}" ]] && SESSION_FLAG=(--session-id "$CLAUDE_CODE_SESSION_ID")
  python3 -I "$PLUGIN_DIR/scripts/lanes.py" mailbox park "${BASH_REMATCH[1]}" --lane "${BASH_REMATCH[2]}" --reason context-guard ${SESSION_FLAG[@]+"${SESSION_FLAG[@]}"} >/dev/null 2>&1 || true
fi
exit 0
