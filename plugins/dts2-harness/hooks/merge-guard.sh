#!/usr/bin/env bash
# PreToolUse (Bash, no `if` filter: the filter is best-effort and never matches `bash -c "git push ..."`, `/usr/bin/git`, `env git`,
# `sudo git`, `eval` or `xargs` forms): refuse a force-push, and a merge or push to a protected branch unless a lane's merge-go.md
# names the head and the base commit. The payload is read first and only a line naming push or merge reaches python, which keeps
# the hook cheap. Denials are printed as PreToolUse JSON and appended to .harness/merge-guard.log.
# Fails open only when python3 is missing; every other path is decided by scripts/guard.py.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting merge_guard true)" == "true" ]] || exit 0
payload="$(cat)"
[[ "$payload" == *push* || "$payload" == *merge* ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
printf '%s' "$payload" | python3 -I "$PLUGIN_DIR/scripts/guard.py" --mode merge --cwd .
