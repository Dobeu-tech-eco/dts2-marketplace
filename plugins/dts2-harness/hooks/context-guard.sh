#!/usr/bin/env bash
# PostToolUse (all tools): stop a run on a context spike before the plan checkpoint, or when started in a member repo. Never fails the session.
set -uo pipefail
source "$(dirname "$0")/lib-settings.sh"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
TOOL_CALLS_DEFAULT=250
MB_DEFAULT=12
BYTES_PER_MB=1048576
[[ "$(setting enabled true)" == "true" ]] || exit 0
[[ "$(setting context_guard true)" == "true" ]] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
INPUT="$(cat 2>/dev/null || true)"
json_field() { printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get(sys.argv[1], "") or "")
except Exception: pass' "$1" 2>/dev/null || true; }
number_or() { [[ "$1" =~ ^[0-9]+$ ]] && echo "$1" || echo "$2"; }
TRANSCRIPT="$(json_field transcript_path)"
SESSION="$(json_field session_id)"
CWD="$(json_field cwd)"
SESSION="${SESSION//[^A-Za-z0-9_-]/}"
[[ -n "$SESSION" ]] || exit 0
[[ -n "$CWD" && -d "$CWD" ]] || CWD="$PWD"
MARKER_DIR="${TMPDIR:-/tmp}"
scope_field() { timeout 4 python3 "$PLUGIN_DIR/scripts/scope-check.py" "$CWD" 2>/dev/null | python3 -c 'import json,sys
try: v = json.load(sys.stdin).get(sys.argv[1]); print("" if v is None else v)
except Exception: pass' "$1" 2>/dev/null || true; }
fire() {
  local trigger="$1" details="$2" marker="$MARKER_DIR/dts2-guard-$SESSION-$1"
  [[ -e "$marker" ]] && return 0
  : > "$marker" 2>/dev/null || true
  python3 -c 'import json,sys
msg = ("dts2-harness CONTEXT GUARD (%s): %s. STOP: do not dispatch or continue any agent. "
       "Follow the run skill'"'"'s '"'"'Context guard and pivot'"'"' section now: write .harness/state.md and the handoff file, "
       "run scope-check, then /dts2-harness:setup (workspace re-link if a manifest exists) and resume with run resume.") % (sys.argv[1], sys.argv[2])
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))' "$trigger" "$details" 2>/dev/null || true
}
SCOPE="$(scope_field scope)"
ROOT="$(scope_field workspaceRoot)"
if [[ "$SCOPE" == "workspace-member" ]]; then
  fire misplaced "cwd $CWD is a member repo of workspace $ROOT"
  exit 0
fi
[[ -f "$TRANSCRIPT" ]] || exit 0
TOOL_LIMIT="$(number_or "$(setting context_guard_tool_calls "$TOOL_CALLS_DEFAULT")" "$TOOL_CALLS_DEFAULT")"
MB_LIMIT="$(number_or "$(setting context_guard_mb "$MB_DEFAULT")" "$MB_DEFAULT")"
CALLS="$(grep -cE '"type": ?"tool_use"' "$TRANSCRIPT" 2>/dev/null || true)"
CALLS="$(number_or "$CALLS" 0)"
BYTES="$(wc -c < "$TRANSCRIPT" 2>/dev/null | tr -d ' ' || true)"
BYTES="$(number_or "$BYTES" 0)"
MB=$(( BYTES / BYTES_PER_MB ))
(( CALLS >= TOOL_LIMIT || MB >= MB_LIMIT )) || exit 0
EFFECTIVE="${ROOT:-$CWD}"
compgen -G "$EFFECTIVE/.harness/runs/*/plan.md" >/dev/null 2>&1 && exit 0
fire spike "$CALLS tool calls / $MB MB with no plan checkpoint reached"
exit 0
