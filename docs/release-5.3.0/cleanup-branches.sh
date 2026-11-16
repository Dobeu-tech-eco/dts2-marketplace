#!/usr/bin/env bash
# Delete merged and stale branches after the dt 5.3.0 release PR merges, leaving only main and dev.
# Run from a machine where `gh` is signed in with delete rights on the repo.
#   bash docs/release-5.3.0/cleanup-branches.sh --dry-run   # list what would go
#   bash docs/release-5.3.0/cleanup-branches.sh             # delete
# A branch that still has an open PR is always skipped.
set -euo pipefail

readonly REPO="Dobeu-tech-eco/dts2-marketplace"
readonly KEEP=("main" "dev")
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

command -v gh >/dev/null 2>&1 || { echo "gh is not installed or not on PATH" >&2; exit 2; }
gh auth status >/dev/null 2>&1 || { echo "gh is not signed in: run gh auth login" >&2; exit 2; }

is_kept() {
  local name="$1"
  for keep in "${KEEP[@]}"; do
    [[ "$name" == "$keep" ]] && return 0
  done
  return 1
}

has_open_pr() {
  local name="$1" count
  count="$(gh pr list --repo "$REPO" --head "$name" --state open --json number --jq 'length')"
  [[ "$count" != "0" ]]
}

deleted=0
skipped=0
while IFS= read -r branch; do
  [[ -z "$branch" ]] && continue
  if is_kept "$branch"; then
    continue
  fi
  if has_open_pr "$branch"; then
    echo "skip   $branch (open PR)"
    skipped=$((skipped + 1))
    continue
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "would delete $branch"
  else
    gh api -X DELETE "repos/$REPO/git/refs/heads/$branch" >/dev/null
    echo "delete $branch"
  fi
  deleted=$((deleted + 1))
done < <(gh api --paginate "repos/$REPO/branches" --jq '.[].name')

echo "done: $deleted deleted$([[ "$DRY_RUN" == "1" ]] && echo ' (dry run)'), $skipped skipped with open PRs"
echo "remaining branches:"
gh api --paginate "repos/$REPO/branches" --jq '.[].name'
