#!/usr/bin/env bash
# SubagentStop (builder|reviewer|verifier) and PostToolUse (SubagentHandback): block once, with the exact missing sections, when a
# report lacks the sections its contract names. Usage: subagent-report.sh stop|handback. Never fails the session.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting subagent_report_check true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 -I "$PLUGIN_DIR/scripts/subagent_report.py" --event "${1:-stop}"
