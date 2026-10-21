#!/usr/bin/env bash
# PostToolUse hook: on `gh pr create|edit`, make sure the PR body has a change receipt and the
# repo's PR template has the section. Never blocks: every failure goes to stderr and exits 0.
# The `git push` below is the plugin's one deliberate push, limited to the PR's head branch.
set -uo pipefail

RECEIPT_MARKER="## Change receipt"
ORG_TEMPLATE_API="repos/Dobeu-tech-eco/.github/contents/.github/pull_request_template.md"
LOCAL_TEMPLATE=".github/pull_request_template.md"
ORG_CACHE="${TMPDIR:-/tmp}/dts2-org-template.cache"
COMMIT_MESSAGE="chore: add change receipt to PR template"
PR_COMMAND_PATTERN='gh pr (create|edit)'
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GH="${DTS2_GH_BIN:-gh}"

warn() { echo "dts2-harness pr-receipt: $*" >&2; }

is_pr_command() {
  local payload="$1"
  printf '%s' "$payload" | python3 -c '
import json, re, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(1)
command = (data.get("tool_input") or {}).get("command", "")
ok = data.get("tool_name") == "Bash" and re.search(sys.argv[1], command)
sys.exit(0 if ok else 1)
' "$PR_COMMAND_PATTERN"
}

pr_field() {
  printf '%s' "$1" | python3 -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1],""))' "$2"
}

latest_run_receipt() {
  local dir
  dir=$(ls -1d .harness/runs/*/ 2>/dev/null | sort | tail -1)
  [[ -n "$dir" && -f "${dir}receipt.md" ]] && echo "${dir}receipt.md"
}

# Template receipt with the tests table replaced by "not recorded".
fallback_receipt() {
  awk '
    /^### Tests run/ { print; print ""; print "not recorded"; print ""; skip=1; next }
    /^### / { skip=0 }
    !skip { print }
  ' "$PLUGIN_DIR/templates/receipt.md"
}

build_receipt() {
  local run_receipt
  run_receipt=$(latest_run_receipt)
  if [[ -n "$run_receipt" ]]; then cat "$run_receipt"; else fallback_receipt; fi
}

add_receipt_to_pr() {
  local number="$1" body="$2" file
  file=$(mktemp "${TMPDIR:-/tmp}/dts2-pr-body.XXXXXX") || { warn "cannot create temp file"; return 0; }
  { printf '%s\n\n' "$body"; build_receipt; } > "$file"
  "$GH" pr edit "$number" --body-file "$file" >/dev/null || warn "gh pr edit failed for PR #$number"
  rm -f "$file"
}

org_has_receipt() {
  if [[ -f "$ORG_CACHE" ]]; then [[ "$(cat "$ORG_CACHE")" == "yes" ]]; return; fi
  local answer="no"
  if "$GH" api "$ORG_TEMPLATE_API" -H "Accept: application/vnd.github.raw" 2>/dev/null | grep -qF "$RECEIPT_MARKER"; then
    answer="yes"
  fi
  echo "$answer" > "$ORG_CACHE" 2>/dev/null
  [[ "$answer" == "yes" ]]
}

repo_has_receipt() {
  [[ -f "$LOCAL_TEMPLATE" ]] && grep -qF "$RECEIPT_MARKER" "$LOCAL_TEMPLATE"
}

write_template() {
  mkdir -p "$(dirname "$LOCAL_TEMPLATE")"
  if [[ -f "$LOCAL_TEMPLATE" ]]; then
    { printf '\n'; cat "$PLUGIN_DIR/templates/receipt.md"; } >> "$LOCAL_TEMPLATE"
  else
    cp "$PLUGIN_DIR/templates/pr-template.md" "$LOCAL_TEMPLATE"
  fi
}

ensure_template() {
  local branch="$1"
  repo_has_receipt && return 0
  org_has_receipt && return 0
  write_template || { warn "cannot write $LOCAL_TEMPLATE"; return 0; }
  git add "$LOCAL_TEMPLATE" && git commit -q -m "$COMMIT_MESSAGE" || { warn "git commit failed"; return 0; }
  [[ -n "$branch" ]] || { warn "no head branch; not pushing"; return 0; }
  git push -q origin "$branch" || warn "git push origin $branch failed"
}

main() {
  local payload view number body branch
  payload=$(cat)
  is_pr_command "$payload" || return 0
  command -v "$GH" >/dev/null 2>&1 || { warn "gh not found ($GH); skipping"; return 0; }
  view=$("$GH" pr view --json number,body,headRefName) || { warn "gh pr view failed"; return 0; }
  number=$(pr_field "$view" number)
  body=$(pr_field "$view" body)
  branch=$(pr_field "$view" headRefName)
  if [[ "$body" != *"$RECEIPT_MARKER"* ]]; then add_receipt_to_pr "$number" "$body"; fi
  ensure_template "$branch"
}

main || true
exit 0
