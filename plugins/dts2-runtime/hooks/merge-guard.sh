#!/usr/bin/env bash
# PreToolUse (Bash, no `if` filter: the filter is best-effort and never matches `bash -c "git push ..."`, `/usr/bin/git`, `env git`,
# `sudo git`, `eval` or `xargs` forms): refuse a force-push, and a merge or push to a protected branch unless a lane's merge-go.md
# names the head and the base commit. The payload is read first and only a line naming push or merge reaches python, which keeps
# the hook cheap. Denials are printed as PreToolUse JSON and appended to .harness/merge-guard.log.
# Fails open only when python3 is missing; every other path is decided by scripts/guard.py.
set -uo pipefail
# --deny-exit-code=2 (written by hooks_install.py for Muse, which blocks only on exit 2) is passed on to the guard.
deny_exit=0
for arg in "$@"; do [[ "$arg" == --deny-exit-code=2 ]] && deny_exit=2; done
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)}"
[ -n "$PLUGIN_ROOT" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${PLUGIN_ROOT}/hooks/lib-settings.sh"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting merge_guard true)" == "true" ]] || exit 0
payload="$(cat)"
[[ "$payload" == *push* || "$payload" == *merge* ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
printf '%s' "$payload" | python3 -I "${PLUGIN_ROOT}/scripts/guard.py" --mode merge --cwd . --deny-exit-code "$deny_exit"
