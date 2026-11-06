# Phase 3 — execute, close out, report

## Model rule
The lead only coordinates and signs off. Every rebase, fix or CI change is done by a worker with the model named explicitly in the dispatch: `sonnet` for code, CI and rebases, `haiku` for mechanical edits (changelog lines, version bumps, comments). One worker per PR, each in its own worktree:
`git worktree add -b sweep/<pr> ../wt-sweep-<pr> origin/<head>`.
Workers never push to the default branch, never merge, never spawn agents. The lead verifies each result (diff and green CI) before merging and records who verified it.

## Order
```
python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sweep.py" order --inventory .harness/pr-sweep/<stamp>/inventory.json
```
It returns `{"waves": [[...], ...]}`: stack bases before their children, PRs touching shared files one per wave, everything else in one parallel wave. Run the PRs of a wave at the same time, one worker each. Waves run in order.

## Per PR
1. GREEN: merge with `gh pr merge <n> --merge`. If checks are still pending and the repo allows auto-merge, `gh pr merge <n> --auto --merge`; otherwise watch with `gh pr checks <n> --watch`.
2. NEEDS REBASE / STACKED: a worker rebases onto the updated base (retarget a stacked child to the default branch first), pushes its own PR branch, CI re-runs, then merge. Pushing a rebased PR branch uses `--force-with-lease` only on a branch this run created or that the PR's author is the signed-in user; any other branch is a hard stop.
3. CI RED: `phase-2-ci-triage.md`.
4. SUPERSEDED / DEAD: `gh pr close <n> --comment "<why, link to the replacement>"`.
5. After each merge: `git fetch`, rebase the next dependent PR, re-run its CI before merging it.
6. Record every outcome with `pr_sweep.py record --dir <dir> --pr N --bucket B --action <merged|closed|rebased|waiting|left> [--sha S] [--reason R] [--ci V] --worker <model> --verified-by <lead|worker>`.

## Close out
- Delete head branches of merged and closed PRs where permitted (`gh api -X DELETE repos/<o>/<r>/git/refs/heads/<branch>`); a denial goes in the report, not around it.
- `git worktree remove` every `../wt-sweep-*` and `git worktree prune`.
- Write the report: `pr_sweep.py report --dir .harness/pr-sweep/<stamp>`.

## Report
`report.md` leads with the result:
1. Open PRs before -> after, merged, closed.
2. Waiting on the user (bucket H), each with the exact decision or action needed.
3. Branches not deleted.
4. The table: PR, bucket, action, merge SHA or close reason, CI verdict.
5. Which worker model did each change and who verified it.

Print the first three to the user. With `--run <stamp>` stop here and hand the result back to autopilot; otherwise continue to `phase-4-optimise-ci.md` only if `--optimise-ci` was given.
