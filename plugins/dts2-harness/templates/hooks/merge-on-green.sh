#!/usr/bin/env bash
# dts2 optional hook: Stop. Reports check status of the open PR for this branch. Never merges, never blocks.
set -uo pipefail

command -v gh >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
cat >/dev/null

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
pr="$(gh pr view --json number,state,statusCheckRollup 2>/dev/null)" || exit 0
[ -n "$pr" ] || exit 0

printf '%s' "$pr" | python3 -I -c 'import json,sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if data.get("state") != "OPEN":
    sys.exit(0)
checks = data.get("statusCheckRollup") or []
good = {"SUCCESS", "NEUTRAL", "SKIPPED"}
green = failing = 0
for c in checks:
    verdict = c.get("conclusion") or c.get("state") or ""
    if verdict in good:
        green += 1
    elif verdict in {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"}:
        failing += 1
total = len(checks)
if total == 0:
    tail = "no checks reported yet"
elif green == total:
    tail = "all green, ready to merge when you decide"
elif failing:
    tail = f"{failing} failing, not ready to merge"
else:
    tail = "waiting on the rest, ready to merge once green"
number = data.get("number")
msg = f"PR #{number}: {green} of {total} checks green, {tail}."
print(json.dumps({"systemMessage": msg}))' 2>/dev/null
exit 0
