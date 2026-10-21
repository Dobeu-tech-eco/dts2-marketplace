#!/usr/bin/env bash
# SessionStart: put the most recent harness lessons, open state items and open action items into context. Never fails the session.
set -uo pipefail
source "$(dirname "$0")/lib-settings.sh"
MAX_LESSONS_DEFAULT=10
MAX_OPEN_ITEMS=5
LESSONS=".harness/lessons.md"
STATE=".harness/state.md"
ACTION_ITEMS=".harness/action-items.md"
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting lessons_inject true)" == "true" ]] || exit 0
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
