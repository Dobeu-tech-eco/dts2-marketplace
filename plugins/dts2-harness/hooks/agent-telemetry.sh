#!/usr/bin/env bash
# Agent telemetry (SubagentStart/Stop, Agent PreToolUse, Edit/Write/Agent/Handback PostToolUse, Stop, SessionStart, SessionEnd).
# Usage: agent-telemetry.sh <event>. Records agent starts/stops, detects incidents, injects lessons. Never fails the session.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting incident_capture true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
python3 -I "$PLUGIN_DIR/scripts/incidents.py" hook "${1:-stop}" 2>/dev/null || true
exit 0
