---
name: dt-ship
description: "Run the /dt-ship procedure shipped in this plugin. Ship a branch as a pull request: pre-check, repo checks, secret scan, verifier and reviewer, receipt, a required roadmap link, an open-PR cap, push, open PR; then sweep stale branches and fold safe strays after one confirmatio..."
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-ship/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Ship — pre-check, verify, PR, then tidy branches and PRs

`/dt-ship [base]` takes whatever is on the current branch and turns it into a reviewed pull request. `base` defaults to `dev` when it exists on the remote, else the default branch. Ship never merges; merging is the user's call (or `autopilot`'s, under its own gate).

**One pipeline.** When `.harness/end-state.md` has `status: approved`, steps 2 to 6 run end to end without a separate question between them: commit the tree, check, scan, review, write the receipt, open the PR. The only stops are a real finding (a secret, a `do_not_touch` path, a red check, a CRITICAL or HIGH review finding), a PR with no roadmap link (step 5), and the repo being at its open-PR cap (step 6). With no approved end state, ship still asks at each decision as before.

## 1. Pre-check
Run the run skill's **Pre-check (every run command)** exactly as written there (`scripts/skills-check.py <repo> --fix`). An upgrade it starts stops ship until the user reloads; the handoff records `Next action: /dt-ship <base>` so the re-run resumes here.

## 2. Branch and tree
1. `git status --porcelain`. Uncommitted work → show `git status --short` and ask once: commit it into this PR, leave it out (stash with `git stash push -u -m dts2-ship-<stamp>`, record the stash SHA from `git stash list --format='%H %gs'`), or stop. That stash is restored with `git stash apply <sha>` (then dropped by its tag) whenever ship ends, including every early stop below, never only at step 8.
2. On the default branch, `dev`, or a detached HEAD → create `ship/<YYYYMMDD>-<slug from the change>` from the current HEAD with `git switch -c`; never commit to `main` or `dev` directly.
3. `git fetch origin`. If the branch is behind `origin/<base>` and the user says yes: rebase only when the branch has never been pushed (`git rev-parse --abbrev-ref @{u}` fails); otherwise merge `origin/<base>` into it, because rebasing a pushed branch would need a force-push. A conflict → install and run `/resolve-merge-conflicts` (see Companion skills in `.harness/discipline.md`) before touching it by hand; if it cannot resolve cleanly, stop and hand it to the user.

## 3. Pre-checks (evidence, not claims)
Read `.harness/config.yaml` `commands:`. Run `verify` when it exists, else each of `typecheck`, `lint`, `test`, `build` that is set; an empty command is skipped and named as skipped. Keep pass/fail/skip counts for the receipt. Then on `git diff origin/<base>...HEAD`:
- **Secret scan.** `gitleaks detect --no-git --redact -s <changed files>` when gitleaks is installed; otherwise grep the added lines for key-shaped strings (`-----BEGIN`, `sk_live_`, `sk-`, `AKIA`, `ghp_`, `xox[bp]-`, `eyJ` JWTs, `password=`/`secret=` with a literal value). Any hit blocks ship: show file:line with the value redacted and stop.
- **do_not_touch.** Any changed path matching `do_not_touch` in config blocks ship unless the user explicitly says it is intended.
- **Repo checks.** Run `.harness/checks.sh` when it exists, and any repo-declared checker the repo's CLAUDE.md requires before a PR.

A failing check → show it and ask once: fix now (a builder on the owning files, up to the 5-round cap from the run skill) or stop. Never open a PR on a red check unless the user overrides; the override goes in Open risks.
A builder fix report whose first line is `PARTIAL: hit turn cap at <step>` is not a fix: re-dispatch the builder on the remaining steps or a fresh builder, inside the 5-round cap.

## 4. Review
Dispatch, in one message, `dt:verifier` (seat: sign-off, `model: opus`) to confirm the checks against HEAD and look for stubs, and one `dt:reviewer` (seat: advisory, `standard`) on the whole diff with `.harness/review-checklist.md`. CRITICAL or HIGH findings → show them and ask: fix, ship anyway (recorded in Open risks), or stop.

A verifier or reviewer report whose first line is `PARTIAL: hit turn cap at <step>` has not passed: treat it as no verdict, re-run that agent (narrower scope or a fresh agent), and do not continue to step 5 until a complete report comes back.

## 5. Receipt and PR body
1. Build the receipt from `$PLUGIN/templates/receipt.md` into `.harness/runs/ship-<stamp>/receipt.md`: tests from step 3, `Merge danger` (one-way door when the change reaches a public or production branch, deletes data or rewrites history, else two-way; blast radius = who or what breaks if it is wrong), `Evidence` (a test that failed before and passes now, a command's output, or a screenshot pair; or `none` with the reason), verdict from step 4, `Approved by` = `$(git config user.name), $(date +%Y-%m-%d)` (invoking ship is the approval), steps outside this change and open risks from `.harness/action-items.md`, rollback point = `git merge-base HEAD origin/<base>`.
2. If the repo has no `.github/pull_request_template.md`, copy `$PLUGIN/templates/pr-template.md` there and include it in this PR. If it has one without `## Change receipt`, the `pr-receipt.sh` hook appends the section; do not add it twice.
3. Install and run `/pr` (see Companion skills) for the title and summary, then fill the template: Summary, Linked work (end-state section or feature slug, an open action-item id), the `Follows:` line naming the open PR this branch was cut from (or `none`), and the `Merge:` line that reads `merge commit only`, Type, Pre-checks boxes ticked only for checks that actually ran green, Consensus `n/a: human approved`, and the receipt. Write it to `.harness/runs/ship-<stamp>/pr-body.md`. Title in Conventional Commits form. The numbers of any PRs this one folds are **not** known yet; they are added to the Linked work line in step 7, after the fold, so the roadmap check below runs on the section or action-item id alone.
4. **Roadmap link (required).** Every PR names a real end-state section number or an open action-item id, so the work traces to the approved roadmap. Check it: `python3 "$PLUGIN/scripts/dt_gate.py" bridge ship_links.py --repo . check --body .harness/runs/ship-<stamp>/pr-body.md`. Read the JSON `ok` field it prints. When `ok` is `false` (exit 1), do not open the PR: add the right `section <n>` or action-item id to the Linked work line and run it again, or, when the change genuinely belongs to no section (a chore in a repo with no end state), add an action item for it first (`/dt-action-items`) and link that. A repo with no `.harness/end-state.md` at all is the one exception: the check passes on a `feature/` slug, and the Linked work line names the branch. If the command cannot run at all — `ship_links.py` is not present on this surface, or a bridge returns BLOCKED instead of the JSON — treat the gate as unavailable rather than failed: name the linked section or action item in the body by hand, note `roadmap link not machine-checked` in Open risks, and continue.

Before merge is requested, run `python3 "$PLUGIN/scripts/dt_gate.py" bridge pr_loop.py --repo . check --base origin/main --file-items`. Fix or file every item it lists, then paste the printed `## Loop gate` block into the PR body. CI fails the release gate without it.

## 6. Push and open
**Open-PR cap (per repo).** Before pushing, count the repo's open PRs (`gh pr list --state open --limit 200 --json number --jq length`; `--limit 200` so the count is not capped at the default 30) and check them against the cap: `python3 "$PLUGIN/scripts/dt_gate.py" bridge ship_links.py cap --config .harness/config.yaml --open <count>`. The cap is `ship: open_pr_cap:` in `.harness/config.yaml`, else `autopilot: open_pr_cap:`, else 5. Read the JSON `exceeded` field. When it is `true` (exit 1), do not open a new PR: say the repo is at its open-PR cap, run the sweep in step 7 to clear or fold what is open, and come back. This counts every open PR in the repo, not only this run's. If the command cannot run — `ship_links.py` is not present, or a bridge returns BLOCKED — treat the cap as unavailable: note `open-PR cap not checked` in Open risks and continue.

Invoking ship is the user's request to push this branch and open its PR, so: `git push -u origin "<branch>"` (never `--force` and never to `main` or `dev`; a branch that is Lovable- or v0-connected is never force-pushed), then `gh pr create --base "<base>" --title "<title>" --body-file .harness/runs/ship-<stamp>/pr-body.md`. Print the PR URL, then `gh pr checks <n> --watch` with a 20-minute cap and report pass/fail per check. A failing check → show `gh run view <id> --log-failed` (last 40 lines) and offer a follow-up fix; never re-run CI or merge without an explicit yes.

## 7. Sweep branches and PRs to main and dev
Goal: only `main` and `dev` remain, with every other branch either merged, folded into an open PR, or explicitly kept.
1. Gather: `gh pr list --state open --limit 200 --json number,title,headRefName,baseRefName,isDraft,updatedAt,mergeable,author,isCrossRepository` (`--limit 200` so the list is not capped at the default 30), `git branch -r --merged origin/main`, `git for-each-ref refs/remotes/origin --format='%(refname:short) %(committerdate:short)'`, and the local `git worktree list`.
2. **Never touched** (always **keep**, in every mode): `main`, `dev`, the default branch, every branch protected on the remote (`gh api repos/<owner>/<repo>/branches --jq '.[] | select(.protected) | .name'`), `gh-pages`, `release*`, `staging`, `production`, a branch checked out in any worktree, a cross-repository (fork) PR's branch, Dependabot and Renovate PRs, branches connected to Lovable or v0, and any local branch with commits not on its remote (`git rev-list @{u}..<branch>` non-empty, or no upstream at all while it has commits not on `origin/<base>`).
3. Classify every other branch:
   - **merged**: fully contained in `origin/main` (or `origin/dev`) → delete.
   - **redundant PR**: `git diff origin/<base>...<head>` is empty (its changes are already in base) → close with a comment naming the merge that contains them. A PR that only looks like a duplicate of another is never closed automatically; it is listed as **review** for the user.
   - **foldable PR**: a stray the fold planner clears. Build `strays.json` as a JSON list, one object per candidate PR from step 7.1, each with: `number` (PR number), `author` (the PR's `author.login`, a GitHub login — never `git config user.name`), `base` (`baseRefName`), `files` (that PR's changed files, from `gh pr view <n> --json files --jq '[.files[].path]'`), `mergeable` (`mergeable`, which is `MERGEABLE`/`CONFLICTING`/`UNKNOWN`), `ci` (`green` only when every check of its `statusCheckRollup` passed — map anything else, including no checks, to `pending` or `red`), `draft` (`isDraft`), and `cross_repo` (`isCrossRepository`). Write the ship branch's own changed files, one per line, to `changed.txt`. Then: `python3 "$PLUGIN/scripts/dt_gate.py" bridge ship_fold.py plan --input strays.json --author <ship branch author login> --base <base> --files-file changed.txt --self <this PR's number>`. It returns `foldable` (same author, same base, not draft, not a fork, mergeable, green CI, files a subset of the ship branch's, not this PR) and `listed` (each with the first reason it failed). The planner fails closed: any field it cannot confirm leaves the stray out of `foldable`. Every `listed` stray stays open and is shown with its reason; a red, conflicting, or draft stray is never folded.

     **Folding safely.** Fold only the `foldable` ones, into this one PR, **one commit per folded stray** — each commit the stray's *entire* PR delta, not just its tip — so any single fold can be reverted. For each, in number order: re-check `mergeable` and CI right before touching it (`gh pr view <n> --json mergeable,statusCheckRollup`) and skip it if either has changed; apply the whole PR with `git cherry-pick -n "origin/<base>..<stray head SHA>"` — the range folds every commit of the PR, because cherry-picking the tip SHA alone applies only the last commit, drops the stray's earlier changes, and can conflict when the tip depends on them — then record it as one commit whose message names the source: `git commit -m "fold #<n> (<stray head SHA>)"`. On any conflict, `git cherry-pick --abort` and stop folding (leave that stray and the rest open, list them). After the commit, confirm it carries the stray's change (`git show --stat HEAD`) before moving on. When all folds are in, push once; then for each folded stray re-scan `git diff origin/<base>...HEAD` to confirm its change is present and wait for green CI on the ship PR before closing it with a comment `Folded into #<ship PR> (<fold commit SHA>)`. Never delete a folded stray's branch, and never close a PR the planner did not return in `foldable`. Record one action item `cleanup <date>` naming the folded PR numbers, and add those numbers to this PR's Linked work line now (step 5 left them out).
   - **stale branch**: no open PR, last commit older than 30 days, not merged, not in the never-touched list → delete (tip SHA recorded first).
   - **review**: anything else (an open PR updated in the last 14 days counts as active) → listed, untouched.
4. Show the table (`branch | PR | class | action`) and ask once: `Apply this cleanup? (yes / edit / skip)`. Nothing is deleted, closed or folded without that yes. Under `autopilot` there is no question, and the sweep is narrower: it deletes only branches autopilot itself created (`dts2/<stamp>/step-*` whose PR is merged) and closes nothing; every other row is reported for the user.
5. Apply: `gh pr close <n> --comment "<reason>"`, `git push origin --delete "<branch>"`, `git branch -D "<branch>"` for local copies (quote every branch name so a ref that looks like a flag is treated as data), `git worktree prune`. Write every deleted branch's name and tip SHA to `.harness/runs/ship-<stamp>/cleanup.md` before deleting it.

## 8. After ship
Append `- <date> shipped PR #<n> (<title>), receipt .harness/runs/ship-<stamp>/receipt.md; cleanup <k> branches, <c> PRs closed, <f> folded` to `.harness/state.md` → `## Decisions`; update the end-state section's status to `in-progress` (review) when the PR links one; restore any stash from step 2; run `python3 "$PLUGIN/scripts/dt_gate.py" bridge handoff-write.py <repo>`. Then run the evolve sweep exactly as the run skill's After ship step says.

## Guardrails
- Never merge, never push to `main` or `dev`, never force-push, never rewrite published history.
- Never delete `main` or `dev`, a branch with an open PR the sweep did not close, a fork's branch, or a branch checked out in any worktree.
- Never print a secret's value; the scan redacts.
- Every destructive sweep action is recorded with its SHA before it runs.
