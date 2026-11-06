### Added

- Auto-merge when green: a new human-only approval kind `merge_policy` (`"merge_policy": ["auto-when-green"]` under `dts2_approvals` in `.claude/settings.local.json`) is a standing grant. With it, the policy gate lets `gh pr merge <n> --auto --squash --match-head-commit <sha>` through when the sha is the head `lanes.py merge-go-step` recorded, the live PR head still equals it, the PR touches none of the new `auto_merge_never_paths` in `templates/policy.json` (workflows, `policy.json`, settings files, `.env*`, migrations) and the base branch has required status checks (branch protection or a ruleset). GitHub does the merge, and only when those checks are green. Every lookup failure denies, and every denial says what to add.
- `approvals.standing_auto_merge()` and `tests/test_auto_merge_policy.py`.

### Changed

- Autopilot phase 2 step 4 arms auto-merge pinned to the head (no `--delete-branch`), records `auto-merge-armed`, confirms `MERGED` with `gh pr view` on the next pass, and re-runs `merge-go-step` if the head moves. A plain `gh pr merge` without `--auto` still needs the per-PR approval. The merge-approval text in COMMANDS, GUIDE, INVENTORY and the run operations skill describes both paths and the one-time setup.
