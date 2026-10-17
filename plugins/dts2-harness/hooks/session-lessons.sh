#!/usr/bin/env bash
# SessionStart: put the most recent harness lessons into context. Never fails the session.
set -uo pipefail
source "$(dirname "$0")/lib-settings.sh"
MAX_LESSONS_DEFAULT=10
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting lessons_inject true)" == "true" ]] || exit 0
LESSONS=".harness/lessons.md"
[[ -f "$LESSONS" ]] || exit 0
max="$(setting lessons_max "$MAX_LESSONS_DEFAULT")"
[[ "$max" =~ ^[0-9]+$ ]] || max="$MAX_LESSONS_DEFAULT"
echo "dts2-harness lessons for this repo (apply when relevant):"
grep -E '^- ' "$LESSONS" | tail -n "$max"
[[ -s ".harness/lessons-inbox.md" ]] && echo "(Unreviewed lesson candidates exist. Run the dts2-harness learn skill to consolidate them.)"
exit 0
