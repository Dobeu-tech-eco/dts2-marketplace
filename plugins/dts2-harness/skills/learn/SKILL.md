---
name: learn
description: Consolidate reviewer and verifier findings into durable per-repo lessons in .harness/lessons.md that the planner, builders, and reviewers read on every future run, and prune stale or duplicate lessons. Use after harness runs, when the user says learn from this, remember this mistake, update lessons, or when the session-start notice says lesson candidates are waiting.
---

# Learn — the harness lessons loop

Lessons live in the repo, so they travel with the code and every agent and machine sees the same list.

## Inputs
- `.harness/lessons-inbox.md` — raw candidates from `run` and the SDK runner.
- `.harness/runs/*/3-review.md` from recent headless runs.
- Anything the user just said to remember.
- The current `.harness/lessons.md`.

## Steps
1. Read the inbox and current lessons.
2. For each candidate decide: new lesson, merge into an existing one (bump its count), or drop (one-off, too vague, or already covered).
3. Write each lesson as one line that an agent can act on:
   `- [L-014] Validate webhook signatures before parsing the body. (seen 3x, last 2026-10-17, source: run 20261017-0012)`
   Rules start with a verb, name the specific thing, and avoid "be careful".
   A lesson seen twice (same normalized text, or same file and rule) is offered for promotion: a line in `.harness/checks.sh` (sourced by the Stop hook), a test skeleton in the repo's test directory, or a `review-checklist.md` entry. Record `lives at <path>` on the lesson.
4. Keep the list short: at most 40 lessons. Past that, drop the oldest single-occurrence lessons first and tell the user which ones.
5. Show the diff of `lessons.md` and wait for approval before writing (interactive use). In auto mode, skip the wait; see Auto mode.
6. After writing, clear the processed entries from the inbox.

## Auto mode
When `run` invokes this skill after a ship (it does so unless `auto_learn` is `false` in `.claude/dts2-harness.local.md`), skip the approval wait in step 5, write `lessons.md` and any promotion, clear the processed inbox entries, and return the `lessons.md` diff for the ship summary. Interactive use keeps the approval wait.

## Optional: promote across repos
If the same lesson appears in two or more repos of a workspace, offer to add it to the workspace manifest under `shared_lessons:` so `run` applies it everywhere.

## Guardrails
- Never edit plugin hooks. Promotion writes only to `.harness/checks.sh`, the repo's test directory, or `review-checklist.md`.
- Never store secrets, tokens, customer data, or personal details in lessons.
- Never invent a lesson the evidence does not support.
