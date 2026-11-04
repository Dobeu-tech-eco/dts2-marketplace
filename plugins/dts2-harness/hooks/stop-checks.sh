#!/usr/bin/env bash
# Stop: refresh .harness/handoff/latest.md, then quick typecheck and lint on changed files. Non-blocking, warnings go to stderr.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
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
CACHE_EXCLUDE=':(exclude).harness/cache'
state_dir() {
  if [[ -d ".harness" ]]; then
    echo ".harness/cache"
    return 0
  fi
  echo "${TMPDIR:-/tmp}/dts2-stop-$(printf '%s' "$PWD" | cksum | cut -d' ' -f1)"
}
STATE_DIR="$(state_dir)"
mkdir -p "$STATE_DIR" 2>/dev/null || true
FINGERPRINT_FILE="$STATE_DIR/stop-fingerprint"
TSBUILDINFO_FILE="$STATE_DIR/tsbuildinfo"
compute_fingerprint() {
  git diff HEAD --stat -- . "$CACHE_EXCLUDE" 2>/dev/null || true
  git status --porcelain --untracked-files=normal -- . "$CACHE_EXCLUDE" 2>/dev/null || true
}
FINGERPRINT=""
IN_GIT=false
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IN_GIT=true
  FINGERPRINT="$(compute_fingerprint)"
  [[ -n "$FINGERPRINT" ]] || exit 0
  if [[ -f "$FINGERPRINT_FILE" && "$(cat "$FINGERPRINT_FILE")" == "$FINGERPRINT" ]]; then
    exit 0
  fi
fi
save_fingerprint() {
  [[ "$IN_GIT" == "true" ]] || return 0
  printf '%s' "$FINGERPRINT" >"$FINGERPRINT_FILE" 2>/dev/null || true
}
run_checks() {
  [[ -f ".harness/checks.sh" ]] && { timeout "$CHECK_TIMEOUT_S" bash ".harness/checks.sh" 2>&1 | tail -20 >&2 || true; }
  [[ -f "package.json" && -d "node_modules" ]] || return 0
  command -v npx >/dev/null 2>&1 || return 0
  if [[ -f "tsconfig.json" ]]; then
    timeout "$CHECK_TIMEOUT_S" npx tsc --noEmit --incremental --tsBuildInfoFile "$TSBUILDINFO_FILE" 2>&1 | tail -20 >&2 || true
  fi
  if ls .eslintrc* eslint.config.* >/dev/null 2>&1; then
    changed=$(git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null | grep -E '\.(ts|tsx|js|jsx)$' || true)
    if [[ -n "$changed" ]]; then
      echo "$changed" | xargs timeout "$CHECK_TIMEOUT_S" npx eslint --no-error-on-unmatched-pattern 2>&1 | tail -20 >&2 || true
    fi
  fi
}
run_checks
save_fingerprint
exit 0
