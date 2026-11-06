#!/usr/bin/env bash
# PreToolUse (Bash, head and sons): the declarative policy gate (G-70). scripts/policy_gate.py evaluates templates/policy.json:
# force-push, --admin, deploy CLIs, gh secret, vercel env, a bare env, repo deletes are refused; gh pr merge and a push to the
# default branch need a human approval in .claude/settings.local.json; staging everything without a secret scanner is red in an
# unattended run. Denials are printed as PreToolUse JSON and appended to the policy-gate log.
# Per-agent rules: with DTS2_AGENT set the same script also judges file tools (hooks.json passes `files`); without it those
# calls return at once. Fails open only when python3 is missing; every other path is decided by the script.
set -uo pipefail
[[ "${1:-}" != "files" || -n "${DTS2_AGENT:-}" ]] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting policy_gate true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
python3 -I "$PLUGIN_DIR/scripts/policy_gate.py" --cwd .
