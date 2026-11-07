#!/usr/bin/env bash
# SessionStart: put the most recent harness lessons, open state items and open action items into context. Never fails the session.
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "${CLAUDE_PLUGIN_ROOT}/hooks/lib-settings.sh"
MAX_LESSONS_DEFAULT=5
MAX_OPEN_ITEMS=5
STAMP_DIR_RE='^[0-9]{8}-[0-9]{1,6}$'  # same shape as state_ids.STAMP_PATTERN
LESSONS=".harness/lessons.md"
STATE=".harness/state.md"
ACTION_ITEMS=".harness/action-items.md"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting lessons_inject true)" == "true" ]] || exit 0
HOOK_INPUT=""
[[ -t 0 ]] || read -r -t 1 -d '' HOOK_INPUT || true
# Only lessons whose paths: globs match the changed files (or that have none), newest few; scope-check.py does the matching.
matching_lessons() {
  local max="$1"
  command -v python3 >/dev/null 2>&1 || return 1
  timeout 4 python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" --lessons "$PWD" 2>/dev/null \
    | python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hook_util.py" lessons-tail "$max" 2>/dev/null
}
print_lessons() {
  local max found
  max="$(setting lessons_max "$MAX_LESSONS_DEFAULT")"
  [[ "$max" =~ ^[1-9][0-9]*$ ]] || max="$MAX_LESSONS_DEFAULT"
  found="$(matching_lessons "$max")" || found="$(grep -E '^- ' "$LESSONS" | tail -n "$max")"
  if [[ -n "$found" ]]; then
    echo "dts2-harness lessons for this repo (apply when relevant):"
    echo "$found"
  fi
  [[ -s ".harness/lessons-inbox.md" ]] && echo "(Unreviewed lesson candidates exist. Run the dts2-harness learn skill to consolidate them.)"
  return 0
}
print_open_items() {
  local items
  items="$(python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hook_util.py" open-items "$STATE" "$MAX_OPEN_ITEMS" 2>/dev/null)"
  [[ -n "$items" ]] || return 0
  echo "dts2-harness state (open items):"
  echo "$items"
}
print_action_items() {
  local items
  items="$(python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hook_util.py" open-action-items "$ACTION_ITEMS" "$MAX_OPEN_ITEMS" 2>/dev/null)"
  [[ -n "$items" ]] || return 0
  echo "dts2-harness action items (open):"
  echo "$items"
}
# After a compact the handoff file is the resume point: print a short pointer (under 300 tokens), not the digest.
run_field() {
  local lease="$1" field="$2"
  python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hook_util.py" json-field "$field" --file "$lease" 2>/dev/null
}
run_phase() {
  local run="$1"
  if [[ -f "$run/receipt.md" ]]; then echo ship
  elif compgen -G "$run/3-*" >/dev/null; then echo review
  elif compgen -G "$run/2-*" >/dev/null; then echo build
  elif compgen -G "$run/*plan*" >/dev/null; then echo plan
  else echo unknown; fi
}
print_compact_pointer() {
  local run="" stamp="none" epoch="none" lane="none" phase="none" lease
  run="$(find .harness/runs -mindepth 1 -maxdepth 1 -type d 2>/dev/null | grep -E "/${STAMP_DIR_RE:1}" | sort | tail -n 1)"
  if [[ -n "$run" ]]; then
    stamp="$(basename "$run")"
    phase="$(run_phase "$run")"
    lease="$(find "$run" -mindepth 2 -maxdepth 2 -name lease.json 2>/dev/null | sort | tail -n 1)"
    if [[ -n "$lease" ]]; then
      lane="$(run_field "$lease" lane)"
      epoch="$(run_field "$lease" epoch)"
    fi
  fi
  echo "dts2-harness resume pointer (context was compacted): stamp $stamp, epoch $epoch, lane $lane, phase $phase."
  echo "Next: read .harness/handoff/latest.md (the rewritten handoff) before acting."
  echo "rule 1: define done first (outcome plus check method) before planning."
  echo "rule 2: end every run with a receipt listing tests, verdict and rollback point."
  echo "rule 3: cap fix rounds at five, then escalate with what failed."
}
if [[ "$HOOK_INPUT" =~ \"source\"[[:space:]]*:[[:space:]]*\"compact\" ]]; then
  print_compact_pointer
  exit 0
fi
# Lessons, state items and action items are text a person, a son or a past session wrote: they go to the model inside the
# untrusted-content fence council.py defines (A9, G-69), cut at UNTRUSTED_MAX_CHARS. No python3 means nothing is printed.
UNTRUSTED_MAX_CHARS=4000
wrap_untrusted() {
  command -v python3 >/dev/null 2>&1 || return 0
  timeout 4 python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/council.py" wrap - --source "dts2-harness session state" --max-chars "$UNTRUSTED_MAX_CHARS" 2>/dev/null
}
print_state_blocks() {
  [[ -f "$LESSONS" ]] && print_lessons
  [[ -f "$STATE" ]] && print_open_items
  [[ -f "$ACTION_ITEMS" ]] && print_action_items
  return 0
}
state_text="$(print_state_blocks)"
[[ -n "$state_text" ]] && printf '%s\n' "$state_text" | wrap_untrusted
print_scope() {
  local info scope root dir_name
  command -v python3 >/dev/null 2>&1 || return 0
  info="$(timeout 4 python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" "$PWD" 2>/dev/null)" || return 0
  scope="$(printf '%s' "$info" | python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hook_util.py" json-field scope 2>/dev/null)" || return 0
  root="$(printf '%s' "$info" | python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hook_util.py" json-field workspaceRoot --or-empty 2>/dev/null)" || return 0
  dir_name="$(basename "$PWD")"
  case "$scope" in
    workspace-member) echo "dts2-harness scope: you are inside $dir_name, a member of workspace $root. Run /dt:run from $root (run pivots there automatically)." ;;
    none) echo "dts2-harness scope: no harness in this folder; /dt:setup to start." ;;
  esac
}
print_scope || true
exit 0
