#!/usr/bin/env bash
# SessionStart: put the most recent harness lessons and open state items into context. Never fails the session.
set -uo pipefail
source "$(dirname "$0")/lib-settings.sh"
MAX_LESSONS_DEFAULT=10
MAX_OPEN_ITEMS=5
LESSONS=".harness/lessons.md"
STATE=".harness/state.md"
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
[[ -f "$LESSONS" ]] && print_lessons
[[ -f "$STATE" ]] && print_open_items
exit 0
