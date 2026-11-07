#!/usr/bin/env bash
# SessionEnd: release only the lane leases this session took (reasons logout, prompt_input_exit, other), then refresh the handoff.
# Best effort: lease expiry stays the guarantee, so nothing here may fail or hold up the exit.
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${CLAUDE_PLUGIN_ROOT}/hooks/lib-settings.sh"
HANDOFF_TIMEOUT_S=10
RELEASE_TIMEOUT_S=10
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting session_end_release true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
payload="$(cat)"
reason="$(printf '%s' "$payload" | python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hook_util.py" json-field reason 2>/dev/null)"
case "$reason" in logout | prompt_input_exit | other) ;; *) exit 0 ;; esac
printf '%s' "$payload" | timeout "$RELEASE_TIMEOUT_S" python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/session_end.py" >/dev/null 2>&1 || true
if [[ -d ".harness" ]]; then
  timeout "$HANDOFF_TIMEOUT_S" python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" "$PWD" >/dev/null 2>&1 || true
fi
exit 0
