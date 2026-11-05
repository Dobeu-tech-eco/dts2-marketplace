#!/usr/bin/env bash
# SubagentStop (verifier): blocks once when the newest run ledger lacks a check line (N3). Never fails the session.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ "$(setting enabled true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 -I "$PLUGIN_DIR/scripts/agent_events.py" subagent-stop
