#!/usr/bin/env bash
# PreToolUse (Bash, `git *` and `gh *` lines; guard.py returns early on anything that is not a merge or push): refuse a force-push, and a merge or push to a protected branch
# unless a lane's merge-go.md names the head and the base commit. Denials are printed as PreToolUse JSON and appended to .harness/merge-guard.log.
# Fails open only when python3 is missing; every other path is decided by scripts/guard.py.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting merge_guard true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 -I "$PLUGIN_DIR/scripts/guard.py" --mode merge --cwd .
