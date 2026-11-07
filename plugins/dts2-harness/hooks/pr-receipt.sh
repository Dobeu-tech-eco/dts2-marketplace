#!/usr/bin/env bash
# PostToolUse hook: on `gh pr create|edit` (or `gh api .../pulls -X POST`), make sure the PR body has a change receipt and the
# repo's PR template has the section. Never blocks: every failure goes to stderr and exits 0. The logic lives in
# scripts/pr_receipt.py; this wrapper only filters cheaply so an unrelated tool call never starts python3.
set -uo pipefail
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0
# A son hands over a committed branch only (G-64): it neither opens PRs nor pushes, so the receipt hook has nothing to do there.
[[ -n "${DTS2_SON:-}" ]] && exit 0
payload="$(cat)"
# Cheap prefilter: skip python3 unless the payload mentions `gh pr ` or `gh api ` with `/pulls`.
[[ "$payload" == *"gh pr "* || ( "$payload" == *"gh api "* && "$payload" == *"/pulls"* ) ]] || exit 0
printf '%s' "$payload" | python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/pr_receipt.py" || true
exit 0
