#!/usr/bin/env bash
# UserPromptSubmit: capture each prompt typed mid-run into the intake queue and tell the agent how to fold it in. Never blocks a prompt.
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${CLAUDE_PLUGIN_ROOT}/hooks/lib-settings.sh"
INTAKE_TIMEOUT_SECONDS=5
HARNESS_DIR=".harness"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting intake true)" == "true" ]] || exit 0
[[ -d "$HARNESS_DIR" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
HOOK_INPUT=""
[[ -t 0 ]] || read -r -t 1 -d '' HOOK_INPUT || true
[[ -n "$HOOK_INPUT" ]] || exit 0
# intake.py fences the person's words as untrusted content (council.untrusted) and prints only the context text.
printf '%s' "$HOOK_INPUT" | timeout "$INTAKE_TIMEOUT_SECONDS" python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/intake.py" hook --root "$PWD" 2>/dev/null
exit 0
