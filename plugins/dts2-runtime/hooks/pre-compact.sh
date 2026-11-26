#!/usr/bin/env bash
# PreCompact (auto|manual): refresh .harness/handoff/latest.md so the post-compact session can resume from it. Never fails the session.
set -uo pipefail
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)}"
[ -n "$PLUGIN_ROOT" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${PLUGIN_ROOT}/hooks/lib-settings.sh"
HANDOFF_TIMEOUT_S=10
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ -d ".harness" ]] || exit 0
timeout "$HANDOFF_TIMEOUT_S" python3 -I "${PLUGIN_ROOT}/scripts/handoff-write.py" "$PWD" >/dev/null 2>&1 || true
exit 0
