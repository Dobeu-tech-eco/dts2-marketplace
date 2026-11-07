#!/usr/bin/env bash
# PostToolUse (all tools): stop a run on a context spike before the plan checkpoint, or when started in a member repo. Never fails the session.
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${CLAUDE_PLUGIN_ROOT}/hooks/lib-settings.sh"
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
tool_setting="$(setting context_guard_tool_calls "$TOOL_CALLS_DEFAULT")"
mb_setting="$(setting context_guard_mb "$MB_DEFAULT")"
TOOL_LIMIT="$(number_or "$tool_setting" "$TOOL_CALLS_DEFAULT")"
MB_LIMIT="$(number_or "$mb_setting" "$MB_DEFAULT")"
stop_setting="$(setting context_guard_stop false)"
payload="$(cat)"
if [[ "$stop_setting" == "true" ]]; then
  guard_out="$(printf '%s' "$payload" | python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/context-guard.py" --tool-calls "$TOOL_LIMIT" --mb "$MB_LIMIT" --stop)"
else
  guard_out="$(printf '%s' "$payload" | python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/context-guard.py" --tool-calls "$TOOL_LIMIT" --mb "$MB_LIMIT")"
fi
[[ -n "$guard_out" ]] && printf '%s\n' "$guard_out"
# Inside a son (branch prefix dts2/<stamp>/lane-<lane>) a fired guard parks the lane through the mailbox, never by writing phase files.
if [[ -n "$guard_out" && "${DTS2_SON_BRANCH_PREFIX:-}" =~ ^dts2/([^/]+)/lane-(.+)$ ]]; then
  park_stamp="${BASH_REMATCH[1]}"
  park_lane="${BASH_REMATCH[2]}"
  if [[ -n "${CLAUDE_CODE_SESSION_ID:-}" ]]; then
    python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py" mailbox park "$park_stamp" --lane "$park_lane" --reason context-guard --session-id "$CLAUDE_CODE_SESSION_ID" >/dev/null 2>&1 || true
  else
    python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py" mailbox park "$park_stamp" --lane "$park_lane" --reason context-guard >/dev/null 2>&1 || true
  fi
fi
exit 0
