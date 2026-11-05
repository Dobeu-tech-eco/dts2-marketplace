---
name: autopilot
description: Run one or more harness steps end to end without stopping for plan or ship approval. A consensus gate replaces the two human checkpoints, three frontier models from different providers must agree on the plan and again on the build, and Claude Fable 5.1 breaks a split. When three rounds of voting still do not settle a step, a council of five frontier reviewers reads the full voting history, votes, writes a brief for every dissent, and Claude Fable 5.1 as head of council makes the final call (more fixes, strike items, or approve) with a written rationale that answers each dissent. Each step gets its own branch and pull request, which is merged once CI is green before the next step starts, so progress is never lost and check-in shows where it stands. Use when the user says autopilot, run these steps without asking, do sections 3 to 5 unattended, or skip plan review.
---

# Autopilot — the harness pipeline with a consensus gate instead of a human

`/dts2-harness:autopilot <steps>` where `<steps>` is any mix of end-state section numbers (`3,4,7` or `3-5`), action-item ids (`D2`, `S1` when the secret is already present), `feature "<description>"`, or quoted free-text tasks. `autopilot resume` continues the last autopilot run. `autopilot status` prints the progress table and stops.

Invoking autopilot is the user's standing approval for exactly the listed steps: their plans, builds, PRs and merges. It is not approval for anything else.

## Phase files
Read the file for a section only when you reach it; do not read ahead. All files are in this folder. A section number below is the one other skills cite as `autopilot §N`.

| File | Read when |
|---|---|
| `phase-0-preflight.md` | Read `phase-0-preflight.md` (same folder) at the start of a run: section 0, pre-check, preflight, queue, base and merge target, voters, state. |
| `phase-1-gate.md` | Read `phase-1-gate.md` (same folder) when a plan or build goes to the vote: section 1, the consensus gate, and section 1b, the council. |
| `phase-2-step.md` | Read `phase-2-step.md` (same folder) for each step: section 2, plan, build, verify, vote, and section 3, PR, CI, merge. |
| `phase-3-parking.md` | Read `phase-3-parking.md` (same folder) when a step parks, a hard stop fires, or a run resumes: section 4, and section 5a, adjudication. |
| `phase-4-report.md` | Read `phase-4-report.md` (same folder) when the queue is done: section 5, the final report. |
| `son-mode.md` | Read `son-mode.md` (same folder) when the arguments are `--son <stamp>/<lane>`: section 6. A son reads its `brief.md` and this file, and no other phase file. |

## Guardrails
- The council is an escalation, not a shortcut: it sits only after three complete rounds of the normal vote on the same ballot have failed (`council.py eligible`), never earlier and never because one dispatch failed.
- The panel is always three distinct providers at frontier; Fable 5.1 only ever breaks a tie or heads the council. No consensus or council decision, no merge.
- Council seats are always five distinct provider/model pairs, as many providers as are usable; a provider holds a second seat only with a different model, and never with Fable 5.1.
- Every council is written to `.harness/council.md`, `.harness/state.md` and `.harness/lessons.md`: the vote, each member's reasons, the decision and the head's brief.
- The council and its head always get the full history: every round, every ballot, every note from every participant, start to finish. Nothing is summarised away.
- A council decision never overrides a hard stop, a `do_not_touch` path, or branch protection.
- Builders never run a frontier model; frontier is for the votes, the lead, the final review and the verifier, as in the run skill.
- One PR per step or bundle, merged before the next step branches from the updated base, so a stopped run loses at most the step in flight; a PR blocked on a user-input item is the one exception and waits at `pr-open`.
- Never deploy, delete data, force-push, use `--admin`, or bypass branch protection. A tool or policy denial is a park, never something to route around.
- Never print a secret's value.
- A missing user-supplied value is never a reason to stop (section 4); it is a reason for the PR to wait (section 5a), and the run ends with as few open PRs as the bundle rule allows.
