#!/usr/bin/env bash
# dts2 optional hook: Stop. Runs the project test command; blocks the stop when tests fail.
# The command is one line in .claude/hooks/dts2/test-command. Fails open when anything is missing.
set -uo pipefail

command -v python3 >/dev/null 2>&1 || exit 0
input="$(cat)"
active="$(printf '%s' "$input" | python3 -I -c 'import json,sys
try:
    print("yes" if json.load(sys.stdin).get("stop_hook_active") is True else "no")
except Exception:
    print("no")' 2>/dev/null)"
[ "$active" = "yes" ] && exit 0

project="${CLAUDE_PROJECT_DIR:-.}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
file="$project/.claude/hooks/dts2/test-command"
[ -f "$file" ] || file="$here/test-command"
[ -f "$file" ] || exit 0
cmd="$(head -n 1 "$file")"
[ -n "$cmd" ] || exit 0

cd "$project" 2>/dev/null || exit 0
output="$(bash -c "$cmd" 2>&1)"
status=$?
[ "$status" -eq 0 ] && exit 0

printf '%s' "$output" | tail -n 20 | python3 -I -c 'import json,sys
tail = sys.stdin.read()
print(json.dumps({"decision": "block", "reason": "Tests failed: " + tail}))' 2>/dev/null
exit 0
