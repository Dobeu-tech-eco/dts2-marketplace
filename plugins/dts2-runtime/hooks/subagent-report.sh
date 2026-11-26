#!/usr/bin/env bash
# SubagentStop (builder|reviewer|verifier) and PostToolUse (SubagentHandback): block once, with the exact missing sections, when a
# report lacks the sections its contract names. Usage: subagent-report.sh stop|handback. Never fails the session.
set -uo pipefail
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)}"
[ -n "$PLUGIN_ROOT" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${PLUGIN_ROOT}/hooks/lib-settings.sh"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting subagent_report_check true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 -I "${PLUGIN_ROOT}/scripts/subagent_report.py" --event "${1:-stop}"
