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
4. Keep the list short: at most 40 lessons. Past that, drop the oldest single-occurrence lessons first and tell the user which ones.
5. Show the diff of `lessons.md` and wait for approval before writing.
6. After writing, clear the processed entries from the inbox.

## Optional: promote across repos
If the same lesson appears in two or more repos of a workspace, offer to add it to the workspace manifest under `shared_lessons:` so `run` applies it everywhere.

## Guardrails
- Never store secrets, tokens, customer data, or personal details in lessons.
- Never invent a lesson the evidence does not support.
