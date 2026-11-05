#!/usr/bin/env bash
# Stop: refresh .harness/handoff/latest.md, then quick typecheck and lint on changed files. Warnings go to stderr; with stop_checks_block: true a red check blocks the stop once.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
CHECK_TIMEOUT_S=30
HANDOFF_TIMEOUT_S=10
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
HOOK_TIMEOUT_DEFAULT_S=45  # mirrors the Stop timeout in hooks.json when it cannot be read
DEADLINE_MARGIN_S=5        # finish this long before the hook timeout so the fingerprint and block reply still go out
START_S=$SECONDS
hook_timeout_s() {
  local value
  value="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["hooks"]["Stop"][0]["hooks"][0]["timeout"])' "$PLUGIN_DIR/hooks/hooks.json" 2>/dev/null)" || value=""
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || value="$HOOK_TIMEOUT_DEFAULT_S"
  echo "$value"
}
DEADLINE_S=$(( $(hook_timeout_s) - DEADLINE_MARGIN_S ))
# Seconds left before the shared deadline (never negative).
remaining_s() {
  local left=$(( DEADLINE_S - (SECONDS - START_S) ))
  (( left > 0 )) || left=0
  echo "$left"
}
# Per-step budget: CHECK_TIMEOUT_S, but never more than what is left of the shared deadline.
step_budget_s() {
  local left
  left="$(remaining_s)"
  (( left < CHECK_TIMEOUT_S )) && echo "$left" || echo "$CHECK_TIMEOUT_S"
}
[[ "$(setting enabled true)" == "true" ]] || exit 0
write_handoff() {
  [[ -d ".harness" ]] || return 0
  timeout "$HANDOFF_TIMEOUT_S" python3 -I "$PLUGIN_DIR/scripts/handoff-write.py" "$PWD" >/dev/null 2>&1 || true
}
write_handoff
[[ "$(setting stop_checks true)" == "true" ]] || exit 0
EXCLUDES=(':(exclude).harness/cache' ':(exclude).harness/handoff')
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
  { git diff HEAD -- . "${EXCLUDES[@]}" 2>/dev/null
    git ls-files -o --exclude-standard -- . "${EXCLUDES[@]}" 2>/dev/null
    git ls-files -o --exclude-standard -z -- . "${EXCLUDES[@]}" 2>/dev/null | xargs -0 -r git hash-object -- 2>/dev/null
  } | git hash-object --stdin 2>/dev/null || true
}
FINGERPRINT=""
IN_GIT=false
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IN_GIT=true
  RAW="$(git status --porcelain -- . "${EXCLUDES[@]}" 2>/dev/null)"
  [[ -n "$RAW" ]] || exit 0
  FINGERPRINT="$(compute_fingerprint)"
  if [[ -n "$FINGERPRINT" && -f "$FINGERPRINT_FILE" && "$(cat "$FINGERPRINT_FILE")" == "$FINGERPRINT" ]]; then
    exit 0
  fi
fi
TIMED_OUT=false
RED_OUTPUT=""
save_fingerprint() {
  [[ "$IN_GIT" == "true" ]] || return 0
  # A timed-out run saves a partial marker: the next Stop with the same tree runs the checks again instead of skipping.
  local suffix=""
  [[ "$TIMED_OUT" == "true" ]] && suffix=" partial"
  printf '%s%s' "$FINGERPRINT" "$suffix" >"$FINGERPRINT_FILE" 2>/dev/null || true
}
# run_step <command...>: run under the shared deadline; stderr gets the last lines, a non-zero exit is recorded as red.
run_step() {
  local budget out rc
  budget="$(step_budget_s)"
  if (( budget <= 0 )); then
    TIMED_OUT=true
    return 0
  fi
  out="$(timeout "$budget" "$@" 2>&1)"
  rc=$?
  out="$(printf '%s\n' "$out" | tail -20)"
  [[ -n "$out" ]] && printf '%s\n' "$out" >&2
  if (( rc == 124 )); then
    TIMED_OUT=true
  elif (( rc != 0 )); then
    RED_OUTPUT+="$out"$'\n'
  fi
  return 0
}
is_son() { [[ -n "${DTS2_SON:-}" || -n "${DTS2_SON_BRANCH_PREFIX:-}" ]]; }
run_eslint() {
  local changed=() file eslint_bin="node_modules/.bin/eslint"
  [[ -x "$eslint_bin" ]] || return 0
  ls .eslintrc* eslint.config.* >/dev/null 2>&1 || return 0
  while IFS= read -r file; do  # while-read, not mapfile: macOS ships bash 3.2
    [[ -n "$file" ]] && changed+=("$file")
  done < <(git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null | grep -E '\.(ts|tsx|js|jsx)$' || true)
  (( ${#changed[@]} > 0 )) || return 0
  run_step "$eslint_bin" --no-error-on-unmatched-pattern -- "${changed[@]}"
}
run_checks() {
  # Repo-defined checks are the repo's own code: a son (an autonomous run) never executes them from a stop hook.
  if [[ -f ".harness/checks.sh" ]] && ! is_son; then
    run_step bash ".harness/checks.sh"
  fi
  [[ -f "package.json" && -d "node_modules" ]] || return 0
  # Local binaries only: never npx, which can fetch and run a package from the network.
  if [[ -f "tsconfig.json" && -x "node_modules/.bin/tsc" ]]; then
    run_step node_modules/.bin/tsc --noEmit --incremental --tsBuildInfoFile "$TSBUILDINFO_FILE"
  fi
  run_eslint
}
# Reply on stdout with decision:block, once: stop_hook_active in the payload means a block already happened.
maybe_block() {
  [[ -n "$RED_OUTPUT" ]] || return 0
  [[ "$(setting stop_checks_block false)" == "true" ]] || return 0
  local payload=""
  [[ -t 0 ]] || read -r -t 1 -d '' payload || true
  [[ "$payload" =~ \"stop_hook_active\"[[:space:]]*:[[:space:]]*true ]] && return 0
  printf '%s' "$RED_OUTPUT" | python3 -I -c 'import json,sys; print(json.dumps({"decision": "block", "reason": "dts2-harness stop checks are red; fix before stopping:\n" + sys.stdin.read()[-2000:]}))'
}
run_checks
save_fingerprint
maybe_block
exit 0
