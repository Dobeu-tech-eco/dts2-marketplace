---
name: dpp
description: Run several autopilot lanes in parallel as headless sons, one worktree and branch each, under a head that plans lanes from the check-in list, checks feasibility, gets approval, supervises, serialises merges and writes one report. Use when the user says dpp, parallel autopilot, run lanes in parallel, or asks to work several check-in items at once.
---

# dpp — parallel autopilot under one head

`/dts2-harness:dpp [dry-run] [--full] [resume]` is the head. Each lane is `/dts2-harness:autopilot --son <stamp>/<lane>` (autopilot §6) in its own worktree on `dts2/<stamp>/lane-<lane>` (the head works on `dts2/<stamp>/main`), run dir `.harness/runs/<stamp>/<lane>/`. The rules are `discipline.md`, the run and ship skills and autopilot §0–§5a; this file only says what the head does with them.

## 0. Pre-check
1. Pre-check as the run skill defines it (Rule 1); read `.claude/dts2-harness.local.md` for `son_permission_mode`, `builder_timeout_min` and `MAX_BUNDLE`.
2. `dry-run` prints the lane plan from section 2 and stops before any lease, worktree or son.
3. `resume`: run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/task-ledger.py <stamp> --resolved` first; every PR it lists has all its `TASK_` items done, so dispatch a merge son per PR (rebase, verifier with the real value, autopilot §3 merge path, post-merge walkthrough), then continue with section 5 on the lanes still live (autopilot §5a).

## 1. Lane sources
- Candidates are the `outstanding_items` of `check-in.py --json` and nothing else (autopilot §0).
- One exception, "outside check-in": a user-named item passed as `--outside "<item>: <why>"`; the plan marks that lane `outside_checkin` and the report says why.
- `--full` (dpp-full) also admits delegation candidates: a son's open questions, parked items and new action items that an agent can do. Overlapping or out-of-scope candidates are listed under `reported`, never started.

## 2. Lane plan and feasibility
1. Draft `lanes.json` (id, item, files, ids, depends_on, tier) and run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py" plan --from-checkin <check-in.json> --draft lanes.json [--outside ...] [--full] [--max 5]`. It refuses an item not in the check-in list without the marker, caps at five lanes, adds `estimated_spend` (tier × token burn) to every lane, and prints `no further parallel work found` when `--full` finds fewer than the cap.
2. `lanes.py check <manifest>` is the feasibility gate: file sets, ids, schema and lockfile ownership, dependency order, live leases and open PRs. Run it before the plan is proposed and again right before each son starts (Rule 10).
3. Show the plan as a table: lane, item, files, tier, `estimated_spend`, depends_on.

## 3. Approval
- Normal mode: the user approves, edits or drops lanes; nothing starts before that (Rule 2).
- Under autopilot: the plan goes to the vote (autopilot §1), three rounds unsettled → council (autopilot §1b). A lane the council cannot clear is parked as an action item (autopilot §4).

## 4. Start sons
For each approved lane, in dependency order: `lanes.py lease <manifest> --lane <id>` (reserves the file set and ids), `git worktree add`, write `brief.md`, then start the command `lanes.py son-command <manifest> --lane <id> --worktree <path>` prints. Up to five live sons. The head is the only party a son talks to (autopilot §6).

## 5. Supervise
1. Poll `lanes.py status <stamp>` (it reads each lane's `status.json`): per lane `phase`, `updated`, `stale`. `stale: true` past `builder_timeout_min` with no process → mark the lane `incomplete`, reason `stalled`, then send-back, re-plan or escalate (autopilot §4).
2. `questions/<n>.md` is answered by the head alone and never forwarded to the user (autopilot §6); the only thing the user hears from a son is a yes/no the head itself asks at send-back round 3.
3. `lanes.py sendback <stamp> --lane <id> --reason "..."` writes `send-back-<n>.md`; it refuses a third. After two, get a second opinion (a reviewer on another provider, advisory) before escalating.
4. A son touching files outside its lane is out-of-lane: stop it, log the finding, re-plan. Any head override is logged with `$(git config user.name)`, the date and the reason.
5. Continuous dispatch: when a son reports `done` or `incomplete`, fold its lessons and items (section 7), `lanes.py release <stamp> --lane <id>`, re-run `lanes.py plan` and `check` against the new base and live lanes, and start the next eligible lane. In normal mode only lanes from the approved plan are dispatched; a new lane needs section 3 again (`--full` dispatches without asking).
6. A `TASK_` item never slows a lane (autopilot §4); a PR that needs the value waits at `pr-open` with status `blocked` (autopilot §5a).

## 6. Merge order
One merge at a time, dependency order first, then lane order. Before each: rebase the lane branch on the updated base, verifier sign-off on HEAD (Rule 7), then write `merge-go.md` into the lane's run dir; the son merges and runs the post-merge walkthrough (autopilot §3). A dirty rebase goes back to the son as a send-back.

## 7. Lessons and memory roll-up
After each son: its `report.md` lessons go into `.harness/lessons.md` (Rule 8), new D/H/S/Y/P rows into `.harness/action-items.md`, then `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/agent-memory.py"` so the memory files match. Sons never write these (autopilot §6).

## 8. Final report
1. Before the ledger, `lanes.py fold <stamp>` groups `blocked` lanes whose branches rebase cleanly; fold each group into one PR, never split (autopilot §5a).
2. Last step: `task-ledger.py <stamp>` writes `.harness/runs/<stamp>/task-ledger.md`; print it.
3. Write `.harness/runs/<stamp>/dpp-report.md`: a `## Lane <id>` block per lane with every section `lanes.py report-check` expects, then `## Spend` (per lane actual and total) and `## Task ledger`. Run `lanes.py report-check dpp-report.md --lanes a,b`; a missing section is a send-back to that son.
4. Link the report and ledger from `.harness/state.md` and paste the report under "Linked work" in each son PR (Rule 9).

## Guardrails
- Never more than five live sons; never a lane without a lease; never a merge without `merge-go.md`.
- The head never edits lane files itself; it plans, answers, merges and reports (discipline.md).
- Stop at `pr-open` is the default; merges happen only under autopilot's gate or the user's merge.
- A `blocked` PR is never merged by this skill (autopilot §5a).
