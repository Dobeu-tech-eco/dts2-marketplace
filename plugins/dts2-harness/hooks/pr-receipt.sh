#!/usr/bin/env bash
# PostToolUse hook: on `gh pr create|edit`, make sure the PR body has a change receipt and the
# repo's PR template has the section. Never blocks: every failure goes to stderr and exits 0.
# The `git push` below is the plugin's one deliberate push, limited to the PR's own head branch.
set -uo pipefail

RECEIPT_MARKER="## Change receipt"
ORG_TEMPLATE_PATH=".github/pull_request_template.md"
ORG_PATTERN='^[A-Za-z0-9][A-Za-z0-9-]*$'
CONFIG_FILE=".harness/config.yaml"
LOCAL_TEMPLATE=".github/pull_request_template.md"
COMMIT_MESSAGE="chore: add change receipt to PR template"
VIEW_FIELDS="number,body,headRefName,isCrossRepository,headRepositoryOwner,baseRepository"
PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GH="${DTS2_GH_BIN:-gh}"

warn() { echo "dts2-harness pr-receipt: $*" >&2; }

# A son hands over a committed branch only (G-64): it neither opens PRs nor pushes, so the receipt hook has nothing to do there.
[[ -n "${DTS2_SON:-}" ]] && exit 0

# Prints two lines: session id, PR selector (may be empty). Exit 1 when the payload is not a Bash `gh pr create|edit`.
parse_payload() {
  printf '%s' "$1" | python3 -I "$PLUGIN_DIR/scripts/pr_payload.py" parse 2>/dev/null
}

latest_run_receipt() {
  local dir
  # shellcheck disable=SC2012 # run dirs are generated names without odd characters
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
  local body_in receipt_in
  body_in=$(mktemp "${TMPDIR:-/tmp}/dts2-pr-in.XXXXXX") || { warn "cannot create temp file"; return 0; }
  receipt_in=$(mktemp "${TMPDIR:-/tmp}/dts2-pr-rc.XXXXXX") || { rm -f "$body_in"; warn "cannot create temp file"; return 0; }
  printf '%s' "$body" > "$body_in"; build_receipt > "$receipt_in"
  python3 -I "$PLUGIN_DIR/scripts/pr_payload.py" body --body-file "$body_in" --receipt-file "$receipt_in" > "$file"
  rm -f "$body_in" "$receipt_in"
  "$GH" pr edit "$number" --body-file "$file" >/dev/null || warn "gh pr edit failed for PR #$number"
  rm -f "$file"
}

# Org that owns the shared `.github` repo: DTS2_PR_ORG, then a top-level `org:` line in the harness
# config, then the owner of the current repo. Prints nothing when none is known or the value is unsafe.
resolve_org() {
  local org="${DTS2_PR_ORG:-}"
  if [[ -z "$org" && -f "$CONFIG_FILE" ]]; then
    org=$(sed -n 's/^org:[[:space:]]*\([^[:space:]#]*\).*$/\1/p' "$CONFIG_FILE" | head -1)
  fi
  if [[ -z "$org" ]]; then
    org=$("$GH" repo view --json owner --jq .owner.login 2>/dev/null | head -1)
  fi
  [[ "$org" =~ $ORG_PATTERN ]] && printf '%s' "$org"
  return 0
}

# Caches only a definitive answer: the template exists (yes/no section) or the API said 404.
# An unknown org is not an answer: the check is skipped and the local template is used.
org_has_receipt() {
  local org cache out err rc
  org=$(resolve_org)
  [[ -n "$org" ]] || return 1
  cache="${TMPDIR:-/tmp}/dts2-org-template.$org.$1.cache"
  if [[ -f "$cache" ]]; then [[ "$(cat "$cache")" == "yes" ]]; return; fi
  err=$(mktemp "${TMPDIR:-/tmp}/dts2-api-err.XXXXXX") || return 1
  out=$("$GH" api "repos/$org/.github/contents/$ORG_TEMPLATE_PATH" -H "Accept: application/vnd.github.raw" 2>"$err"); rc=$?
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
  local payload parsed session selector view number body branch cross body_file fields
  payload=$(cat)
  # Cheap prefilter: skip python3 unless the payload mentions `gh pr ` or `gh api ` with `/pulls`.
  [[ "$payload" == *"gh pr "* || ( "$payload" == *"gh api "* && "$payload" == *"/pulls"* ) ]] || return 0
  parsed=$(parse_payload "$payload") || return 0
  [[ -n "$parsed" ]] || return 0
  session=$(sed -n 1p <<<"$parsed"); selector=$(sed -n 2p <<<"$parsed")
  command -v "$GH" >/dev/null 2>&1 || { warn "gh not found ($GH); skipping"; return 0; }
  view=$("$GH" pr view ${selector:+"$selector"} --json "$VIEW_FIELDS") || { warn "gh pr view failed"; return 0; }
  body_file=$(mktemp "${TMPDIR:-/tmp}/dts2-pr-view.XXXXXX") || { warn "cannot create temp file"; return 0; }
  fields=$(printf '%s' "$view" | python3 -I "$PLUGIN_DIR/scripts/pr_payload.py" view --body-out "$body_file" 2>/dev/null)
  body=$(cat "$body_file"); rm -f "$body_file"
  number=$(sed -n 1p <<<"$fields"); branch=$(sed -n 2p <<<"$fields"); cross=$(sed -n 3p <<<"$fields")
  [[ -n "$number" ]] || { warn "could not parse gh pr view output; leaving PR untouched"; return 0; }
  if [[ "$body" != *"$RECEIPT_MARKER"* ]]; then add_receipt_to_pr "$number" "$body"; fi
  ensure_template "$session" "$branch" "$cross"
}

main || true
exit 0
