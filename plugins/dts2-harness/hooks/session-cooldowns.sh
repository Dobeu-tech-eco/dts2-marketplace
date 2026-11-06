#!/usr/bin/env bash
# SessionStart: remind the session which agents are cooling down after a usage limit. Never fails the session.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
[[ "$(setting enabled true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
plugin_dir="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
timeout 4 python3 -I "$plugin_dir/scripts/cooldowns.py" session-note 2>/dev/null || true
exit 0
