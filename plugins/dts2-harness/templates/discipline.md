# Harness discipline (Rule 8)

Read by lead, builder, reviewer and verifier. Copied to `.harness/discipline.md` at scaffold.

1. **Define done first.**
   Where it bites: the plan checkpoint will not open without a Done section: outcome plus check method (tests, visual, source, review). Lead refuses to plan without it.
2. **End with a receipt.**
   Where it bites: `receipt.md` lists tests run with pass/fail counts, review verdict, approver, steps outside the change, open risks, rollback point. Shown at the ship checkpoint and appended to the PR body.
3. **Cap fix rounds at three.**
   Where it bites: in `run` and per builder. After three rounds, stop and escalate with what failed; the escalation goes into `.harness/state.md`.
4. **Repeat mistake becomes a check.**
   Where it bites: `learn` detects a lesson seen twice (same normalized text or same file+rule) and offers to promote it: a line in `.harness/checks.sh` (run by the Stop hook), a test skeleton in the repo's test dir, or a line in `review-checklist.md`. It records "lives at <path>" in `lessons.md`.
5. **State outside the chat.**
   Where it bites: `.harness/state.md` holds decisions, failures and open items, appended by run and learn, and read at session start by `session-lessons.sh`. The file is the record.
6. **Auto-add the receipt.**
   Where it bites: `hooks/pr-receipt.sh` runs on `gh pr create` and `gh pr edit`. If the PR body lacks `## Change receipt`, it edits it in, and it adds or extends the PR template in the same branch when neither the repo nor the org default has the section.

## Push exception

Agents never push. The one exception is `pr-receipt.sh`, which pushes only the PR's own branch, and only to add or extend the PR template. It never pushes any other branch.

## Rule 9 — Orchestration (lead on the frontier tier, execution on the cheapest capable tier)

Applies to every agent provider the roster can dispatch; the lead is always the Claude session running `run`.

1. **Lead thinks, workers type.** The lead (frontier tier) decomposes, writes briefs, merges and verifies. It never implements a builder section itself except a trivial single-file change under ~20 lines.
2. **Model by complexity, always explicit.** Every dispatch names a model: `mechanical` → economy, `normal` → standard, `design` → frontier. Lead, verifier and the final whole-diff review run on the frontier tier. Omitting the model is a defect.
3. **Parallel by file set.** Independent builders run in one dispatch message. Two writers never share a file, section or tree.
4. **Briefs, not history.** A worker receives its plan section (goal, owned files, read-only files, acceptance criteria, lessons, test command, commit message, report path) and nothing else. It returns status, commit, a one-line test summary and concerns.
5. **Worker contract.** A worker never pushes, never spawns subagents or reviewers, never grades its own work, never edits outside its file set, and stops to report when the plan is wrong instead of improvising.
6. **Fix loop inside the cap.** Rounds 1–2 resume the same builder; round 3 goes to a fresh builder one tier up; after round 3 the lead stops and escalates (Rule 8.3). Three materially identical failures mean the approach is wrong, not the retry count.
7. **Rulings are written down.** Every decision the lead makes without the user goes to `.harness/state.md` → `## Decisions` as `Ruling: <what> — <why> — <cost if wrong>`. After a context reset the lead trusts `state.md` and `git log`, never memory, and never re-dispatches a builder whose section is marked done.
8. **Hard stops.** The lead asks before: pushing, merging to the default branch, publishing, deploying, purchasing, deleting data or branches, touching credentials, or when the plan is broken enough that every path is a guess. Everything else it rules on and continues.
9. **Scope before spend.** A run checks its scope first (workspace root, member repo, single, none) and pivots to the workspace root when it is inside a member repo. A context spike before the plan checkpoint is a stop signal: stop every agent, write state, re-run setup, resume. Never push through it.

## Rule 10 — Branches, worktrees and pull requests

1. **One run, one branch.** `run` creates `dts2/<stamp>` from the current branch and all builder work lands there. The default branch is never a run's working branch.
2. **One builder, one worktree (git).** In a git repo each builder gets `git worktree add ../<repo>-dts2-<n> -b dts2/<stamp>/b<n> dts2/<stamp>` and works only inside it. `use_worktrees: never` is the explicit opt-out; `always` forces it in workspace mode too.
3. **One builder, one scratch dir (no git).** In a plain folder each builder owns `.harness/wt/<n>/` and a disjoint file list; the lead copies results into place and keeps a diff summary in the run folder.
4. **Lead merges, after green.** When the verifier reports VERIFIED, the lead merges each builder branch into `dts2/<stamp>` in plan order, re-runs the full test suite and every configured check after each merge, resolves conflicts itself, then removes the builder worktrees (`git worktree remove` + branch delete). A conflict it cannot resolve stops the run and goes to the user.
5. **Ship = receipt + user push.** At the ship checkpoint the lead commits on `dts2/<stamp>` with the receipt. The user pushes; `gh pr create --body-file <receipt>` opens the PR; `pr-receipt.sh` guarantees the receipt section and template.
6. **PR checkout for review.** `run review-pr <number>` checks out the PR (`gh pr checkout <number>`), runs only the review and verify phases (walkthrough → reviewers → finish passes → verifier) on the PR diff against its base, and posts the findings as a PR comment on an explicit yes. It never builds or commits on a PR it did not open.
7. **Cleanup.** After the PR merges, `git worktree prune` and delete the local `dts2/<stamp>` branches; `.harness/runs/<stamp>/` stays as the record.
