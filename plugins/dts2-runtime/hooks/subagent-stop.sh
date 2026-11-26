#!/usr/bin/env bash
# SubagentStop (verifier): blocks once when the newest run ledger lacks a check line (N3). Never fails the session.
set -uo pipefail
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)}"
[ -n "$PLUGIN_ROOT" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${PLUGIN_ROOT}/hooks/lib-settings.sh"
[[ "$(setting enabled true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 -I "${PLUGIN_ROOT}/scripts/agent_events.py" subagent-stop
