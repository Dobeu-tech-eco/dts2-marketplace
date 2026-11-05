#!/usr/bin/env bash
# PreCompact (auto|manual): refresh .harness/handoff/latest.md so the post-compact session can resume from it. Never fails the session.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
HANDOFF_TIMEOUT_S=10
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ -d ".harness" ]] || exit 0
timeout "$HANDOFF_TIMEOUT_S" python3 -I "$PLUGIN_DIR/scripts/handoff-write.py" "$PWD" >/dev/null 2>&1 || true
exit 0
