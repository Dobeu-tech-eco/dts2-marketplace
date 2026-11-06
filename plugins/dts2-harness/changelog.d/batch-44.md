### Added

- Merge directly when green: a new human-only approval kind `merge_policy` (`"merge_policy": ["auto-when-green"]` under `dts2_approvals` in `.claude/settings.local.json`) is a standing grant. With it, the policy gate lets `gh pr merge <n> --squash --match-head-commit <sha>` through when the sha is the head `lanes.py merge-go-step` recorded and the live PR head, the PR touches none of the new `auto_merge_never_paths` in `templates/policy.json` (workflows, `policy.json`, settings files, `.env*`, migrations), the base branch requires status checks and every required check is green on that head (read from the check-runs and commit-status APIs). `--auto` is always refused: GitHub native auto-merge is never armed, so every merge runs through the merge mutex. Every lookup failure denies, and every denial says what to do.
- `approvals.standing_auto_merge()` and `tests/test_auto_merge_policy.py`.

### Changed

- Autopilot phase 2 step 4 merges directly with `gh pr merge <n> --squash --match-head-commit <sha>` after `merge-go-step` and green CI (no `--auto`, no `--delete-branch`), and re-runs `merge-go-step` if the head moves. A plain `gh pr merge` without the grant still needs the per-PR approval. The merge-approval text in COMMANDS, GUIDE, INVENTORY and the run operations skill describes both paths; setup is a ruleset or branch protection requiring test and lint, plus the grant. The unattended allowlist permits `gh pr merge*`; the policy gate stays the control.
