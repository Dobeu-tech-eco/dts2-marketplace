---
name: autopilot
description: Run one or more harness steps end to end without stopping for plan or ship approval. A consensus gate replaces the two human checkpoints, three frontier models from different providers must agree on the plan and again on the build, and Claude Fable 5.1 breaks a split. Each step gets its own branch and pull request, which is merged once CI is green before the next step starts, so progress is never lost and check-in shows where it stands. Use when the user says autopilot, run these steps without asking, do sections 3 to 5 unattended, or skip plan review.
---

# Autopilot — the harness pipeline with a consensus gate instead of a human

`/dts2-harness:autopilot <steps>` where `<steps>` is any mix of end-state section numbers (`3,4,7` or `3-5`), action-item ids (`D2`, `S1` when the secret is already present), `feature "<description>"`, or quoted free-text tasks. `autopilot resume` continues the last autopilot run. `autopilot status` prints the progress table and stops.

Invoking autopilot is the user's standing approval for exactly the listed steps: their plans, builds, PRs and merges. It is not approval for anything else.

## 0. Pre-check and preflight
1. Run the run skill's **Pre-check (every run command)**. An upgrade it starts stops autopilot; the handoff records `Next action: /dts2-harness:autopilot resume`.
2. Run the run skill's Preflight steps 0–7 (scope, harness-change guard, config, ignore guard, end state, settings, roster, clean tree). Skip its loop-me check-in and the step-8 clarifying question: autopilot asks nothing mid-run.
3. **Resolve the steps** into an ordered queue: sections by their `depends on` order (a listed section whose dependency is neither `done` nor in the queue → park it, see section 4); action items in the order given; a `feature` step runs the feature skill first and its new sections join the queue right after it.
4. **Base and merge target.** `<base>` is `dev` when it exists on the remote. With no `dev`, the base is the default branch, and a merge there is usually a production deploy (Vercel, Lovable, Netlify and similar deploy the default branch). In that case autopilot merges only if the upfront confirmation below names the default branch explicitly and the user says yes; otherwise every step stops at `pr-open` (consensus passed, CI green, PR left for the user), and any later step that depends on it is parked until that PR is merged.
5. **One upfront confirmation, then none.** If any step touches production deploys, data deletion, auth, or payments (the run skill's Preflight step 9), or the merge target is the default branch, list those steps (and `merges go to <default branch>, which deploys production`) and ask once: `Autopilot will plan, build, merge and continue through these without asking again. Go? (y/n)`. None of these → no question. After this point autopilot never waits for the user unless a hard stop below fires.
6. **Voters.** One seat per provider: claude (Opus) always holds the first, then the first two other providers in the probe's `usable` list whose frontier model is set (`roster.py model --agent <name> --tier frontier` is not `null`; for example codex `gpt-6-astra`, gemini, grok, muse), in roster order. An agent with budget `low` is still eligible, since a vote is a `second-opinion` seat. These three are the **panel**. Claude Fable 5.1 is the **tiebreaker**: dispatched directly with the Agent tool, `subagent_type: dts2-harness:reviewer`, `model: fable`; it never sits on the panel. Fewer than three usable frontier providers → say `Autopilot needs 3 frontier providers; only <n> usable (<names>). Falling back to the normal human checkpoints.` and run `/dts2-harness:run` on the queue instead. Never silently run with a smaller panel.
7. **State.** Take a stamp, write `.harness/autopilot/<stamp>.md` from the table below, and copy it to `.harness/autopilot/latest.md` after every change. This file, the end-state `## Sections` statuses and the handoff are what `/dts2-harness:check-in` reads.

```
# Autopilot <stamp>
panel: claude/opus, <agent>/<model>, <agent>/<model> · tiebreak: claude/fable
| # | step | branch | plan vote | build vote | PR | CI | merged | status |
|---|------|--------|-----------|------------|----|----|--------|--------|
| 1 | section 3: <name> | dts2/<stamp>-s3 | 3-0 | 2-1 → fable approve | #41 | green | 9f3c2a1 | done |
```
Status is one of `queued`, `planning`, `building`, `voting`, `pr-open`, `merged`, `done`, `parked (<action-item id>)`, `stopped`.

## 1. The consensus gate
Used twice per step: on the plan (instead of the Plan checkpoint) and on the built, verified diff (instead of the Ship checkpoint).
1. Write the ballot to `.harness/runs/<stamp>/prompts/vote-<step>-<plan|build>.md`: the step, the end-state excerpt it serves, the lead's plan with its `## Done`, and for the build vote also the diff file, the verifier table and the merged reviewer findings. Ask each voter for exactly one first line `VOTE: APPROVE` or `VOTE: REJECT`, then at most ten findings as `severity file:line — issue — fix`.
2. Dispatch the three panel voters in one message: claude via the Agent tool (`dts2-harness:reviewer`, `model: opus`); every non-Claude voter via the `shell` of `roster.py command --agent <name> --role second-opinion --tier frontier --prompt-file <ballot>` from the repo, its output classified with `roster.py classify` exactly as the run skill does. A voter that comes back `unavailable (billing/quota)` or `seatFailed`, or whose first line is not a `VOTE:` line, is replaced once by the next usable frontier provider; if none is left, the gate falls back to the human checkpoint for that step only and says so.
3. Count each ballot. There are exactly three outcomes:
   - **3-0 APPROVE** → pass.
   - **REJECT majority** (3-0 or 2-1 REJECT) → not passed. Send the union of the rejecting voters' CRITICAL and HIGH findings to the lead (plan vote) or the owning builders (build vote) as one fix round, then vote again. A REJECT majority is never sent to the tiebreaker: Fable can never pass something most of the panel rejected.
   - **2-1 APPROVE** → send the dissenter's CRITICAL and HIGH findings for one fix round and vote again. A second consecutive 2-1 APPROVE is a **split**.
   - **Split** → dispatch the Fable 5.1 tiebreaker (`dts2-harness:reviewer`, `model: fable`) with the ballot, all three verdicts and their findings. `VOTE: APPROVE` → pass; `VOTE: REJECT` → not passed, treated as a REJECT majority. If the Fable dispatch fails or its first line is not a `VOTE:` line, the split is not passed and the step is parked; it never defaults to pass.
4. **Caps, so the gate always ends.** Every not-passed ballot uses one fix round. Plan-vote and build-vote rounds share the run skill's 3-round cap per step (with `/diagnosing-bugs` at round 2 and the fresh pass at the cap, as written there); CI-fix rounds (section 3) have their own cap of 3. At either cap without a pass → park the step (section 4).
5. Record every vote, each voter's agent and model, and the tiebreak in the progress table and in the receipt's `### Review verdict` (for example `consensus 3-0 approve (claude/opus, codex/gpt-6-astra, gemini/<model>)`).

## 2. Per step: plan, build, verify, vote
For each queued step, in order:
1. **Branch** from the freshly fetched base: `git fetch origin` then `git switch -c dts2/<stamp>-<step> origin/<base>` (`dev` when it exists, else the default branch). Never build on a previous step's unmerged branch.
2. Run the run skill's Phase 0 (size, budget), Phase 1 (lead plan) and the **plan vote** in place of the Plan checkpoint. A `feature` step is a step like any other: the feature skill's plan patch is the plan, its approval questions are answered by the plan vote, its PR goes through section 3 and is merged before the sections it added are planned, so they branch from a base that already contains them.
3. Run Phases 2, 3, 3b and 3c exactly as the run skill does: parallel builders on separate file sets in worktrees, never a frontier builder, the walkthrough, axis reviews, the final review, the verifier. Verifier BLOCKED is a not-passed build; it gets the normal fix rounds.
4. Run the **build vote** in place of the Ship checkpoint.
5. Fill the receipt as the run skill's Phase 4 does, with `### Approved by` set to `autopilot consensus (<votes>), <YYYY-MM-DD>` and do the run skill's **After ship** writes (lessons, end-state acceptance boxes, section status `in-progress`, state.md, handoff). The evolve sweep is not run inside autopilot; open harness lessons are listed in the final report.

## 3. Per step: PR, CI, merge
1. Commit with a Conventional Commits message, after the setup-pre-commit gate the run skill names. Push the step branch (`git push -u origin dts2/<stamp>-<step>`; never force, never to `main` or `dev`).
2. Open the PR the way `/dts2-harness:ship` steps 5–6 do (template, `/pr`, receipt), with the template's **Consensus** section filled from the votes. Then post the three verdicts, the tiebreak if any, and the receipt as a PR comment (`gh pr comment <n> --body-file <file>`) so the merge carries visible review evidence.
3. Watch CI: `gh pr checks <n> --watch`, 30-minute cap. A red check → collect `gh run view <id> --log-failed`, send the root cause to the owning builder as a fix round (same 3-round cap), push the fix (a new commit, never a force-push), and run the **build vote** again on the new diff before re-watching CI. A Vercel preview canceled only because a commit is unsigned is non-blocking, as the run skill says.
4. **Merge** when CI is green, the latest build vote passed, and the merge target is allowed (preflight step 4): read the base's protection (`gh api repos/<owner>/<repo>/branches/<base>/protection`); `required_linear_history` or no preference → `gh pr merge <n> --squash --delete-branch`; never `--admin`, never bypass a required review or check. If the merge is refused (a required human review, a missing required check, a permission or tool denial) → do not work around it: park the step with a Decisions action item `merge PR #<n> (autopilot consensus passed, CI green)` and stop every step that depends on it; independent steps continue.
5. After the merge: `git fetch origin`, record the merge SHA in the table, set the section's status to `done` in `.harness/end-state.md` (tick its acceptance boxes the verifier confirmed) on the next step's branch, refresh `.harness/handoff/latest.md` with `Next action: /dts2-harness:autopilot resume`, and remove the step's worktrees and local branches.

## 4. Parking, hard stops, and resume
- **Park** (the step stops, the run continues with steps that do not depend on it): fix-round cap reached, merge refused, a `SECRET NEEDED` with no value present, a dependency parked, a handoff-only builder, a voter-pool collapse for that step, or a failed tiebreak. A pre-check that reports a skill gone upstream never swaps under autopilot: it becomes a Decisions action item listing the ranked candidates, for the user to approve later. Each park gets an action item (Secrets, Decisions or Handoff), its id in the table's status and in the section cell (`payments webhook (D4)`).
- **Hard stop** (the whole autopilot stops, handoff written, `.harness/autopilot/latest.md` status `stopped`): the context guard fires; a change would touch a `do_not_touch` path; a step would deploy to production (other than a default-branch merge the step-5 confirmation approved by name), delete data, force-push, rewrite published history, or push to `main`/`dev` directly; a pre-check upgrade; the user interrupts.
- `autopilot resume` reads `.harness/autopilot/latest.md` and continues at the first step that is not `done` or `parked`, re-running the pre-check first.

## 5. Final report
Print the progress table, then one line each: steps done, parked (with action-item ids and the command that unblocks each), PRs merged, branches left (should be only `main` and `dev`; run `/dts2-harness:ship` step 7's sweep with autopilot's no-ask rule if any step branch survived), open harness lessons for the evolve sweep, and `/dts2-harness:check-in` for the full picture.

## Guardrails
- The panel is always three distinct providers at frontier; Fable 5.1 only ever breaks a tie. No consensus, no merge.
- Builders never run a frontier model; frontier is for the votes, the lead, the final review and the verifier, as in the run skill.
- One PR per step, merged before the next step branches from the updated base, so a stopped run loses at most the step in flight.
- Never deploy, delete data, force-push, use `--admin`, or bypass branch protection. A tool or policy denial is a park, never something to route around.
- Never print a secret's value.
