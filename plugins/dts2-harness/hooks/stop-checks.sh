#!/usr/bin/env bash
# Stop: refresh .harness/handoff/latest.md, then quick typecheck and lint on changed files. Non-blocking, warnings go to stderr.
set -uo pipefail
source "$(dirname "$0")/lib-settings.sh"
CHECK_TIMEOUT_S=30
HANDOFF_TIMEOUT_S=10
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ "$(setting enabled true)" == "true" ]] || exit 0
write_handoff() {
  [[ -d ".harness" ]] || return 0
  timeout "$HANDOFF_TIMEOUT_S" python3 "$PLUGIN_DIR/scripts/handoff-write.py" "$PWD" >/dev/null 2>&1 || true
}
write_handoff
[[ "$(setting stop_checks true)" == "true" ]] || exit 0
[[ -f ".harness/checks.sh" ]] && { timeout "$CHECK_TIMEOUT_S" bash ".harness/checks.sh" 2>&1 | tail -20 >&2 || true; }
[[ -f "package.json" && -d "node_modules" ]] || exit 0
command -v npx >/dev/null 2>&1 || exit 0
if [[ -f "tsconfig.json" ]]; then
  timeout "$CHECK_TIMEOUT_S" npx tsc --noEmit 2>&1 | tail -20 >&2 || true
fi
if ls .eslintrc* eslint.config.* >/dev/null 2>&1; then
  changed=$(git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null | grep -E '\.(ts|tsx|js|jsx)$' || true)
  [[ -n "$changed" ]] && echo "$changed" | xargs timeout "$CHECK_TIMEOUT_S" npx eslint --no-error-on-unmatched-pattern 2>&1 | tail -20 >&2 || true
fi
exit 0
