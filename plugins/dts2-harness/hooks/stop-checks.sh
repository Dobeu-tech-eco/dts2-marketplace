#!/usr/bin/env bash
# Stop: quick typecheck and lint on changed files. Non-blocking, warnings go to stderr.
set -uo pipefail
source "$(dirname "$0")/lib-settings.sh"
CHECK_TIMEOUT_S=30
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting stop_checks true)" == "true" ]] || exit 0
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
