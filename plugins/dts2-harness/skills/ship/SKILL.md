---
name: ship
description: Ship the current branch as a pull request: pre-check, repo checks, secret scan, verifier and reviewer, receipt, PR template, push, open PR; then sweep stale branches and PRs after one confirmation. Never merges. Use for ship, open a PR, or clean up PRs.
---

# Ship — pre-check, verify, PR, then tidy branches and PRs

`/dts2-harness:ship [base]` takes whatever is on the current branch and turns it into a reviewed pull request. `base` defaults to `dev` when it exists on the remote, else the default branch. Ship never merges; merging is the user's call (or `autopilot`'s, under its own gate).

## 1. Pre-check
Run the run skill's **Pre-check (every run command)** exactly as written there (`scripts/skills-check.py <repo> --fix`). An upgrade it starts stops ship until the user reloads; the handoff records `Next action: /dts2-harness:ship <base>` so the re-run resumes here.

## 2. Branch and tree
1. `git status --porcelain`. Uncommitted work → show `git status --short` and ask once: commit it into this PR, leave it out (stash with `git stash push -u -m dts2-ship-<stamp>`, record the stash SHA from `git stash list --format='%H %gs'`), or stop. That stash is restored with `git stash apply <sha>` (then dropped by its tag) whenever ship ends, including every early stop below, never only at step 8.
2. On the default branch, `dev`, or a detached HEAD → create `ship/<YYYYMMDD>-<slug from the change>` from the current HEAD with `git switch -c`; never commit to `main` or `dev` directly.
3. `git fetch origin`. If the branch is behind `origin/<base>` and the user says yes: rebase only when the branch has never been pushed (`git rev-parse --abbrev-ref @{u}` fails); otherwise merge `origin/<base>` into it, because rebasing a pushed branch would need a force-push. A conflict → install and run `/resolve-merge-conflicts` (see Companion skills in `.harness/discipline.md`) before touching it by hand; if it cannot resolve cleanly, stop and hand it to the user.

## 3. Pre-checks (evidence, not claims)
Read `.harness/config.yaml` `commands:`. Run `verify` when it exists, else each of `typecheck`, `lint`, `test`, `build` that is set; an empty command is skipped and named as skipped. Keep pass/fail/skip counts for the receipt. Then on `git diff origin/<base>...HEAD`:
- **Secret scan.** `gitleaks detect --no-git --redact -s <changed files>` when gitleaks is installed; otherwise grep the added lines for key-shaped strings (`-----BEGIN`, `sk_live_`, `sk-`, `AKIA`, `ghp_`, `xox[bp]-`, `eyJ` JWTs, `password=`/`secret=` with a literal value). Any hit blocks ship: show file:line with the value redacted and stop.
- **do_not_touch.** Any changed path matching `do_not_touch` in config blocks ship unless the user explicitly says it is intended.
- **Repo checks.** Run `.harness/checks.sh` when it exists, and any repo-declared checker the repo's CLAUDE.md requires before a PR.

A failing check → show it and ask once: fix now (a builder on the owning files, up to the 3-round cap from the run skill) or stop. Never open a PR on a red check unless the user overrides; the override goes in Open risks.
A builder fix report whose first line is `PARTIAL: hit turn cap at <step>` is not a fix: re-dispatch the builder on the remaining steps or a fresh builder, inside the 3-round cap.

## 4. Review
Dispatch, in one message, `dts2-harness:verifier` (seat: sign-off, `model: opus`) to confirm the checks against HEAD and look for stubs, and one `dts2-harness:reviewer` (seat: advisory, `standard`) on the whole diff with `.harness/review-checklist.md`. CRITICAL or HIGH findings → show them and ask: fix, ship anyway (recorded in Open risks), or stop.

A verifier or reviewer report whose first line is `PARTIAL: hit turn cap at <step>` has not passed: treat it as no verdict, re-run that agent (narrower scope or a fresh agent), and do not continue to step 5 until a complete report comes back.

## 5. Receipt and PR body
1. Build the receipt from `${CLAUDE_PLUGIN_ROOT}/templates/receipt.md` into `.harness/runs/ship-<stamp>/receipt.md`: tests from step 3, verdict from step 4, `Approved by` = `$(git config user.name), $(date +%Y-%m-%d)` (invoking ship is the approval), steps outside this change and open risks from `.harness/action-items.md`, rollback point = `git merge-base HEAD origin/<base>`.
2. If the repo has no `.github/pull_request_template.md`, copy `${CLAUDE_PLUGIN_ROOT}/templates/pr-template.md` there and include it in this PR. If it has one without `## Change receipt`, the `pr-receipt.sh` hook appends the section; do not add it twice.
3. Install and run `/pr` (see Companion skills) for the title and summary, then fill the template: Summary, Linked work (end-state section or feature slug, closed action-item ids, any PRs this one folds from step 7), the `Follows:` line naming the open PR this branch was cut from (or `none`), and the `Merge:` line that reads `merge commit only`, Type, Pre-checks boxes ticked only for checks that actually ran green, Consensus `n/a: human approved`, and the receipt. Write it to `.harness/runs/ship-<stamp>/pr-body.md`. Title in Conventional Commits form.

## 6. Push and open
Invoking ship is the user's request to push this branch and open its PR, so: `git push -u origin <branch>` (never `--force` and never to `main` or `dev`; a branch that is Lovable- or v0-connected is never force-pushed), then `gh pr create --base <base> --title <title> --body-file .harness/runs/ship-<stamp>/pr-body.md`. Print the PR URL, then `gh pr checks <n> --watch` with a 20-minute cap and report pass/fail per check. A failing check → show `gh run view <id> --log-failed` (last 40 lines) and offer a follow-up fix; never re-run CI or merge without an explicit yes.

## 7. Sweep branches and PRs to main and dev
Goal: only `main` and `dev` remain, with every other branch either merged, folded into an open PR, or explicitly kept.
1. Gather: `gh pr list --state open --json number,title,headRefName,baseRefName,isDraft,updatedAt,mergeable,author,isCrossRepository`, `git branch -r --merged origin/main`, `git for-each-ref refs/remotes/origin --format='%(refname:short) %(committerdate:short)'`, and the local `git worktree list`.
2. **Never touched** (always **keep**, in every mode): `main`, `dev`, the default branch, every branch protected on the remote (`gh api repos/<owner>/<repo>/branches --jq '.[] | select(.protected) | .name'`), `gh-pages`, `release*`, `staging`, `production`, a branch checked out in any worktree, a cross-repository (fork) PR's branch, Dependabot and Renovate PRs, branches connected to Lovable or v0, and any local branch with commits not on its remote (`git rev-list @{u}..<branch>` non-empty, or no upstream at all while it has commits not on `origin/<base>`).
3. Classify every other branch:
   - **merged**: fully contained in `origin/main` (or `origin/dev`) → delete.
   - **redundant PR**: `git diff origin/<base>...<head>` is empty (its changes are already in base) → close with a comment naming the merge that contains them. A PR that only looks like a duplicate of another is never closed automatically; it is listed as **review** for the user.
   - **foldable PR**: opened by the same author as the ship branch, same base, touching only files the ship branch also touches, mergeable → offer to fold: cherry-pick its commits onto the ship branch, push, and close it with `Folded into #<n>`.
   - **stale branch**: no open PR, last commit older than 30 days, not merged, not in the never-touched list → delete (tip SHA recorded first).
   - **review**: anything else (an open PR updated in the last 14 days counts as active) → listed, untouched.
4. Show the table (`branch | PR | class | action`) and ask once: `Apply this cleanup? (yes / edit / skip)`. Nothing is deleted, closed or folded without that yes. Under `autopilot` there is no question, and the sweep is narrower: it deletes only branches autopilot itself created (`dts2/<stamp>/step-*` whose PR is merged) and closes nothing; every other row is reported for the user.
5. Apply: `gh pr close <n> --comment <reason>`, `git push origin --delete <branch>`, `git branch -D <branch>` for local copies, `git worktree prune`. Write every deleted branch's name and tip SHA to `.harness/runs/ship-<stamp>/cleanup.md` before deleting it.

## 8. After ship
Append `- <date> shipped PR #<n> (<title>), receipt .harness/runs/ship-<stamp>/receipt.md; cleanup <k> branches, <c> PRs closed, <f> folded` to `.harness/state.md` → `## Decisions`; update the end-state section's status to `in-progress` (review) when the PR links one; restore any stash from step 2; run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" <repo>`. Then run the evolve sweep exactly as the run skill's After ship step says.

## Guardrails
- Never merge, never push to `main` or `dev`, never force-push, never rewrite published history.
- Never delete `main` or `dev`, a branch with an open PR the sweep did not close, a fork's branch, or a branch checked out in any worktree.
- Never print a secret's value; the scan redacts.
- Every destructive sweep action is recorded with its SHA before it runs.
