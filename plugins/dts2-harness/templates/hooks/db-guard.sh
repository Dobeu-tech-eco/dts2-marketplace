#!/usr/bin/env bash
# dts2 optional hook: PreToolUse (Bash). Denies destructive database commands; the user must run them.
# Fails open (exit 0) when python3 is missing or the input cannot be read.
set -uo pipefail

command -v python3 >/dev/null 2>&1 || exit 0
input="$(cat)"

read -r -d '' PY <<'PYEOF' || true
import json
import re
import sys

REASON = "destructive database command blocked by dts2 db-guard; ask the user to confirm and run it themselves"
PATTERNS = (
    r"\bdrop\s+(table|database|schema)\b",
    r"\btruncate\s+(?!-)\S",
    r"\balter\s+table\b[^;]*\bdrop\s+column\b",
    r"\bprisma\s+migrate\s+reset\b",
    r"\bprisma\s+db\s+push\b[^;&|]*--(force-reset|accept-data-loss)\b",
    r"\bsupabase\s+db\s+reset\b",
    r"\bdrizzle-kit\s+drop\b",
    r"\bdb:drop\b",
    r"\bdropdb\b",
)


def deny():
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": REASON}}))
    sys.exit(0)


try:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except Exception:
    sys.exit(0)
if not isinstance(command, str) or not command:
    sys.exit(0)

text = command.lower()
if any(re.search(pattern, text) for pattern in PATTERNS):
    deny()
for found in re.finditer(r"\bdelete\s+from\b", text):
    statement = re.split(r";|&&|\|", text[found.end():], maxsplit=1)[0]
    if not re.search(r"\bwhere\b", statement):
        deny()
PYEOF

printf '%s' "$input" | python3 -I -c "$PY" 2>/dev/null
exit 0
