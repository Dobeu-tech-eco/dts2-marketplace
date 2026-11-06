---
name: autopilot
description: "Run harness steps end to end without human plan or ship approval: a gate of three frontier models from different providers and a council for deadlocks replace the checkpoints. One branch and PR per step. Use for autopilot or run unattended."
---

# Autopilot — the harness pipeline with a consensus gate instead of a human

`/dts2:autopilot <steps>` where `<steps>` is any mix of end-state section numbers (`3,4,7` or `3-5`), action-item ids (`D2`, `S1` when the secret is already present), `feature "<description>"`, or quoted free-text tasks. `autopilot resume` continues the last autopilot run. `autopilot status` prints the progress table and stops.

Invoking autopilot is the user's standing approval for exactly the listed steps: their plans, builds, PRs and merges. It is not approval for anything else.

## Phase files
Read the file for a section only when you reach it; do not read ahead. All files are in this folder. A section number below is the one other skills cite as `autopilot §N`.

| File | Read when |
|---|---|
| `phase-0-preflight.md` | Read `phase-0-preflight.md` (same folder) at the start of a run: section 0, pre-check, preflight, queue, base and merge target, voters, state. |
| `phase-1-gate.md` | Read `phase-1-gate.md` (same folder) when a plan or build goes to the vote: section 1, the consensus gate, and section 1b, the council. |
| `phase-2-step.md` | Read `phase-2-step.md` (same folder) for each step: section 2, plan, build, verify, vote, and section 3, PR, CI, merge. |
| `phase-3-parking.md` | Read `phase-3-parking.md` (same folder) when a step parks, a hard stop fires, or a run resumes: section 4; and at the end of every run, before `phase-4-report.md`, for section 5a, adjudication (it runs on every run, parked or not). |
| `phase-4-report.md` | Read `phase-4-report.md` (same folder) when the queue is done and section 5a adjudication (`phase-3-parking.md`) has run: section 5, the final report. |
| `son-mode.md` | Read `son-mode.md` (same folder) when the arguments are `--son <stamp>/<lane>`: section 6. A son reads its `brief.md` and this file first, then loads the other phase files on demand as it reaches each section, exactly as the head does (sections 0 to 5a apply to it), except that it never runs the steps `son-mode.md` reserves for the head. |
| `son-contract.md` | Read `son-contract.md` (same folder) with `son-mode.md`: the mailbox rules every son obeys (no own stamp, protected records, need-human, parks, merge-go check, fresh rules). |

## Guardrails
- The council is an escalation, not a shortcut: it sits only after three complete rounds of the normal vote on the same ballot have failed (`council.py eligible`), never earlier and never because one dispatch failed.
- The panel is always three distinct providers at frontier; Fable 5.1 only ever breaks a tie or heads the council. No consensus or council decision, no merge.
- Council seats are always five distinct provider/model pairs, as many providers as are usable; a provider holds a second seat only with a different model, and never with Fable 5.1.
- Every council is written to `.harness/council.md`, `.harness/state.md` and `.harness/lessons.md`: the vote, each member's reasons, the decision and the head's brief.
- The council and its head always get the full history: every round, every ballot, every note from every participant, start to finish. Nothing is summarised away.
- A council decision never overrides a hard stop, a `do_not_touch` path, or branch protection.
- Builders never run a frontier model; frontier is for the votes, the lead, the final review and the verifier, as in the run skill.
- One PR per step or bundle, merged before the next step branches from the updated base, so a stopped run loses at most the step in flight; a PR blocked on a user-input item is the one exception and waits at `pr-open`.
- Merge loop (G-78): before each merge the head runs `lanes.py base-health <stamp>` (the fetched `origin/<base>` must be green; `merge-go` refuses while it is red or has moved) and `lanes.py merge-mutex <stamp> --lane <id> --op acquire` before the rebase; the mutex is released (`--op release`) only after the post-merge walkthrough passes. A failed walkthrough goes to `lanes.py fix-attempt`: up to `post_merge_fix_attempts` (default 2) fixes, then it opens one revert PR, which merges under the same gate (a production deploy on merge still needs its per-merge yes) or the run parks.
- Folded PRs (G-79): after `fold --apply <group> --pr <n>` the head runs `lanes.py fold-close <stamp>`, which closes each superseded original with a link to the new PR.
- Integration lane (G-80): files that route to the integration lane (lockfiles, migrations, route tables, barrels, shared globs) are never fought over. `lanes.py status` and `report` print each routing record: what was refused, the reason, the alternative (the integration lane) and the override (`lanes.py override <lane>`, which needs the owner's recorded approval). Show it to the owner; never hide it.
- PR pile-up: at most `open_pr_cap` (default 5) of this run's PRs open before a new step starts; `/dts2:pr-sweep --run <stamp>` works the queue down mid-run and once more at the end.
- Never deploy, delete data, force-push, use `--admin`, or bypass branch protection. A tool or policy denial is a park, never something to route around.
- Never print a secret's value.
- A missing user-supplied value is never a reason to stop (section 4); it is a reason for the PR to wait (section 5a), and the run ends with as few open PRs as the bundle rule allows.
