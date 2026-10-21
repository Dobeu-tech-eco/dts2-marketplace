#!/usr/bin/env bash
# PostToolUse hook: on `gh pr create|edit`, make sure the PR body has a change receipt and the
# repo's PR template has the section. Never blocks: every failure goes to stderr and exits 0.
# The `git push` below is the plugin's one deliberate push, limited to the PR's own head branch.
set -uo pipefail

RECEIPT_MARKER="## Change receipt"
ORG_TEMPLATE_API="repos/Dobeu-tech-eco/.github/contents/.github/pull_request_template.md"
LOCAL_TEMPLATE=".github/pull_request_template.md"
COMMIT_MESSAGE="chore: add change receipt to PR template"
VIEW_FIELDS="number,body,headRefName,isCrossRepository,headRepositoryOwner,baseRepository"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GH="${DTS2_GH_BIN:-gh}"

warn() { echo "dts2-harness pr-receipt: $*" >&2; }

# Prints three lines: session id, PR selector (may be empty), PR URL from the tool response (may be empty).
# Prints nothing (exit 1) when the payload is not a Bash `gh pr create|edit` command.
parse_payload() {
  printf '%s' "$1" | python3 -c '
import json, re, shlex, sys
PR_CMD = re.compile(r"(?:^|[;&|\n])[ \t]*gh pr (create|edit)\b([^;&|\n]*)")
VALUE_FLAGS = {"--title", "-t", "--body", "-b", "--body-file", "-F", "--base", "-B", "--head", "-H",
               "--label", "-l", "--assignee", "-a", "--reviewer", "-r", "--milestone", "-m",
               "--project", "-p", "--template", "-T", "--add-label", "--remove-label", "--add-assignee",
               "--remove-assignee", "--add-reviewer", "--remove-reviewer", "--add-project",
               "--remove-project"}
SELECTOR = re.compile(r"^[A-Za-z0-9._/#:@%~+-]+$")
try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(1)
command = (data.get("tool_input") or {}).get("command", "")
match = PR_CMD.search(command) if data.get("tool_name") == "Bash" else None
if not match:
    sys.exit(1)
try:
    tokens = shlex.split(match.group(2))
except ValueError:
    tokens = []
selector, skip = "", False
for token in tokens:
    if skip:
        skip = False
        if match.group(1) == "create" and prev in ("--head", "-H"):
            selector = token
        continue
    if token.startswith("-"):
        prev = token
        skip = "=" not in token and token in VALUE_FLAGS
        if token.startswith("--head=") and match.group(1) == "create":
            selector = token.split("=", 1)[1]
        continue
    if match.group(1) == "edit" and not selector:
        selector = token
if not SELECTOR.match(selector):
    selector = ""
response = data.get("tool_response")
text = response.get("stdout", "") if isinstance(response, dict) else (response or "")
url = re.search(r"https://[^\s]+/pull/\d+", str(text))
if match.group(1) == "create" and not selector and url:
    selector = url.group(0)
session = re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id", "")))
print(session or "nosession")
print(selector)
' 2>/dev/null
}

# pr_field <json> <field>: prints the field, or nothing when the JSON does not parse.
pr_field() {
  printf '%s' "$1" | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin).get(sys.argv[1], "")
except (ValueError, AttributeError):
    value = ""
print(str(value).lower() if isinstance(value, bool) else value)
' "$2" 2>/dev/null
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
  { [[ -n "$body" ]] && printf '%s\n\n' "$body"; build_receipt; } > "$file"
  "$GH" pr edit "$number" --body-file "$file" >/dev/null || warn "gh pr edit failed for PR #$number"
  rm -f "$file"
}

# Caches only a definitive answer: the template exists (yes/no section) or the API said 404.
org_has_receipt() {
  local cache="${TMPDIR:-/tmp}/dts2-org-template.$1.cache" out err rc
  if [[ -f "$cache" ]]; then [[ "$(cat "$cache")" == "yes" ]]; return; fi
  err=$(mktemp "${TMPDIR:-/tmp}/dts2-api-err.XXXXXX") || return 1
  out=$("$GH" api "$ORG_TEMPLATE_API" -H "Accept: application/vnd.github.raw" 2>"$err"); rc=$?
  if [[ $rc -eq 0 ]]; then
    if grep -qF "$RECEIPT_MARKER" <<<"$out"; then echo yes > "$cache"; rm -f "$err"; return 0; fi
    echo no > "$cache"
  elif grep -qiE "not found|404" "$err"; then
    echo no > "$cache"
  fi
  rm -f "$err"
  return 1
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

can_push_branch() {
  local branch="$1" cross="$2"
  [[ -n "$branch" && "$cross" != "true" ]] || return 1
  [[ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" == "$branch" ]]
}

ensure_template() {
  local session="$1" branch="$2" cross="$3"
  repo_has_receipt && return 0
  org_has_receipt "$session" && return 0
  write_template || { warn "cannot write $LOCAL_TEMPLATE"; return 0; }
  git add "$LOCAL_TEMPLATE" || { warn "git add failed"; return 0; }
  if ! can_push_branch "$branch" "$cross"; then
    echo "pr-receipt: PR template staged; commit and push it to ${branch:-the PR branch} yourself (branch mismatch or fork PR)" >&2
    return 0
  fi
  git commit -q -m "$COMMIT_MESSAGE" -- "$LOCAL_TEMPLATE" || { warn "git commit failed"; return 0; }
  git push -q origin "HEAD:refs/heads/$branch" || warn "git push origin $branch failed"
}

main() {
  local payload parsed session selector view number body branch cross
  payload=$(cat)
  parsed=$(parse_payload "$payload") || return 0
  [[ -n "$parsed" ]] || return 0
  session=$(sed -n 1p <<<"$parsed"); selector=$(sed -n 2p <<<"$parsed")
  command -v "$GH" >/dev/null 2>&1 || { warn "gh not found ($GH); skipping"; return 0; }
  view=$("$GH" pr view ${selector:+"$selector"} --json "$VIEW_FIELDS") || { warn "gh pr view failed"; return 0; }
  number=$(pr_field "$view" number)
  [[ -n "$number" ]] || { warn "could not parse gh pr view output; leaving PR untouched"; return 0; }
  body=$(pr_field "$view" body)
  branch=$(pr_field "$view" headRefName)
  cross=$(pr_field "$view" isCrossRepository)
  if [[ "$body" != *"$RECEIPT_MARKER"* ]]; then add_receipt_to_pr "$number" "$body"; fi
  ensure_template "$session" "$branch" "$cross"
}

main || true
exit 0
