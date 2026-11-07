#!/usr/bin/env bash
# PermissionDenied: appends a Handoff action item naming the denied tool. Never fails the session.
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${CLAUDE_PLUGIN_ROOT}/hooks/lib-settings.sh"
[[ "$(setting enabled true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/agent_events.py" permission-denied
