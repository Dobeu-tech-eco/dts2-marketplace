#!/usr/bin/env bash
# SessionStart: remind the session which agents are cooling down after a usage limit. Never fails the session.
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${CLAUDE_PLUGIN_ROOT}/hooks/lib-settings.sh"
[[ "$(setting enabled true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
timeout 4 python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/cooldowns.py" session-note 2>/dev/null || true
exit 0
