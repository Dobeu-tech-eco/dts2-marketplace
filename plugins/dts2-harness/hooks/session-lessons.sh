#!/usr/bin/env bash
# SessionStart: put the most recent harness lessons, open state items and open action items into context. Never fails the session.
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib-settings.sh
source "$(dirname "$0")/lib-settings.sh"
MAX_LESSONS_DEFAULT=10
MAX_OPEN_ITEMS=5
LESSONS=".harness/lessons.md"
STATE=".harness/state.md"
ACTION_ITEMS=".harness/action-items.md"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting lessons_inject true)" == "true" ]] || exit 0
HOOK_INPUT=""
[[ -t 0 ]] || read -r -t 1 -d '' HOOK_INPUT || true
print_lessons() {
  local max
  max="$(setting lessons_max "$MAX_LESSONS_DEFAULT")"
  [[ "$max" =~ ^[0-9]+$ ]] || max="$MAX_LESSONS_DEFAULT"
  echo "dts2-harness lessons for this repo (apply when relevant):"
  grep -E '^- ' "$LESSONS" | tail -n "$max"
  [[ -s ".harness/lessons-inbox.md" ]] && echo "(Unreviewed lesson candidates exist. Run the dts2-harness learn skill to consolidate them.)"
}
print_open_items() {
  local items
  items="$(sed -n '/^## Open items/,/^## /{ /^## /d; p; }' "$STATE" | grep -E '^- ' | tail -n "$MAX_OPEN_ITEMS")"
  [[ -n "$items" ]] || return 0
  echo "dts2-harness state (open items):"
  echo "$items"
}
print_action_items() {
  local items
  items="$(awk -F'|' 'NF > 3 { for (i = NF - 1; i > NF - 4 && i > 1; i--) { s = $i; gsub(/^[ \t]+|[ \t]+$/, "", s); if (s ~ /^(open|done)/) break } if (s ~ /^open/) print }' "$ACTION_ITEMS" | head -n "$MAX_OPEN_ITEMS")"
  [[ -n "$items" ]] || return 0
  echo "dts2-harness action items (open):"
  echo "$items"
}
# After a compact the handoff file is the resume point: print a short pointer (under 300 tokens), not the digest.
run_field() {
  local lease="$1" field="$2"
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$lease" "$field" 2>/dev/null
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
  run="$(find .harness/runs -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -n 1)"
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
  echo "Next: read .harness/handoff.md (the rewritten handoff, .harness/handoff/latest.md) before acting."
  echo "rule 1: define done first (outcome plus check method) before planning."
  echo "rule 2: end every run with a receipt listing tests, verdict and rollback point."
  echo "rule 3: cap fix rounds at three, then escalate with what failed."
}
if [[ "$HOOK_INPUT" =~ \"source\"[[:space:]]*:[[:space:]]*\"compact\" ]]; then
  print_compact_pointer
  exit 0
fi
[[ -f "$LESSONS" ]] && print_lessons
[[ -f "$STATE" ]] && print_open_items
[[ -f "$ACTION_ITEMS" ]] && print_action_items
print_scope() {
  local plugin_dir="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}" info scope root
  command -v python3 >/dev/null 2>&1 || return 0
  info="$(timeout 4 python3 "$plugin_dir/scripts/scope-check.py" "$PWD" 2>/dev/null)" || return 0
  scope="$(printf '%s' "$info" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("scope",""))' 2>/dev/null)" || return 0
  root="$(printf '%s' "$info" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("workspaceRoot") or "")' 2>/dev/null)" || return 0
  case "$scope" in
    workspace-member) echo "dts2-harness scope: you are inside $(basename "$PWD"), a member of workspace $root. Run /dts2-harness:run from $root (run pivots there automatically)." ;;
    none) echo "dts2-harness scope: no harness in this folder; /dts2-harness:setup to start." ;;
  esac
}
print_scope || true
exit 0
