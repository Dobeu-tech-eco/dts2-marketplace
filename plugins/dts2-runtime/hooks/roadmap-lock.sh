#!/usr/bin/env bash
# UserPromptSubmit: when the owner types a lock (`lock roadmap <key>`, or a short message in their own words such as "lock it in"
# while the roadmap waits for approval), record the approval. Runs only on typed text, so the model never writes the approvals file itself (G-63). Prints one confirmation line as context. Never blocks a prompt.
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${CLAUDE_PLUGIN_ROOT}/hooks/lib-settings.sh"
LOCK_TIMEOUT_SECONDS=5
command -v python3 >/dev/null 2>&1 || exit 0
HOOK_INPUT=""
[[ -t 0 ]] || read -r -t 1 -d '' HOOK_INPUT || true
[[ -n "$HOOK_INPUT" ]] || exit 0
printf '%s' "$HOOK_INPUT" | timeout "$LOCK_TIMEOUT_SECONDS" python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/approvals.py" --repo "${CLAUDE_PROJECT_DIR:-$PWD}" grant-from-prompt 2>/dev/null
exit 0
