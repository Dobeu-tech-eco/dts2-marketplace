# Phase 1 — standing rules, inventory, buckets

## Standing rules
Invoking `/dt:pr-sweep` is the user's approval to:
- Merge a PR with a merge commit as soon as its required checks (test and lint at least) are green. No extra review rounds.
- Close a PR that is superseded, duplicate, already merged in substance, or dead, with a comment that says why and links the PR that replaces it.
- Delete a head branch after its PR is merged or closed, where the API allows it. If deletion is denied, list the branch in the report.
- Retarget a stacked PR to the default branch after its base merges, and rebase it.

## Hard stops
Ask first (bucket H) before any of these, and never do them on your own:
- pushing tags
- anything touching secrets or credentials
- deploys or releases
- force-pushing a branch the run did not create
- pushing to the default branch
- deleting, skipping or weakening a valid test or lint rule
- `--admin`, bypassing branch protection or a required review

## Stamp and state
`stamp` is `YYYYMMDD-HHMMSS` (UTC). Create `.harness/pr-sweep/<stamp>/`. With `--run <stamp>`, reuse that stamp and set `--head-prefix dts2/<stamp>/`.

## Inventory (read-only)
```
python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sweep.py" inventory --repo <owner/repo> --stale-days <N> [--head-prefix P] [--author A] --out .harness/pr-sweep/<stamp>
python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sweep.py" classify --inventory .harness/pr-sweep/<stamp>/inventory.json
```
`inventory` uses `gh api` REST only and writes `inventory.json` and `inventory.md`: per PR the number, title, head -> base, draft, author, age, mergeable state, every check, files touched, and the required checks of each base branch (unknown when branch protection is unreadable). `classify` adds the script's bucket, the `stale` flag, `overlaps` (PRs touching the same file), `shared_files` hits (changelogs, version files, INVENTORY, lockfiles) and `candidates` for the two judgment buckets.

## Buckets
Put each PR in exactly one bucket with one line of evidence. The script gives A to D and G; you settle E, F and H from its candidates and the diff.

| | Bucket | Meaning | Action |
|---|---|---|---|
| A | GREEN | checks green, mergeable, not draft | merge |
| B | NEEDS REBASE | conflicts or behind base, CI otherwise fine | worker rebases, re-run CI |
| C | CI RED | a failing or cancelled check | `phase-2-ci-triage.md` |
| D | STACKED | base is another open PR | merge order follows the stack |
| E | SUPERSEDED / DUPLICATE | its changes are on the base already, or another PR does the same better | close with comment |
| F | STALE | no activity in the stale window and not the base of another open PR | still applies and has value: treat as B or C; dead (parked or abandoned step, empty diff, obsolete plan): close with comment |
| G | DRAFT | ready if CI is green and the description says done | otherwise leave and list |
| H | NEEDS ME | touches a hard stop, a failing test that may be a real product bug, or a judgment call evidence cannot settle | wait, with the exact decision needed |

Pending checks: wait for them (auto-merge when allowed, else watch). A PR still running is not red.

Write `buckets.md` (one row per PR: number, bucket, evidence). Show the table, then continue without waiting. Only H waits.
