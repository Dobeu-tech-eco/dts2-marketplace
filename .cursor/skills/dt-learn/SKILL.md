---
name: dt-learn
description: "Consolidate reviewer and verifier findings into durable per-repo lessons in .harness/lessons.md that future runs read, and prune stale ones. Use after runs, or for learn from this, learn promote L-NNN, remember this mistake, or update lessons."
disable-model-invocation: true
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-learn/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

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
   A lesson tied to part of the repo ends with `{paths: src/api/**, *.ts}` (comma-separated globs; `**` crosses directories, `*` stays in one). Session start and `scope-check.py --lessons` print it only when a changed file or an active lane file matches, newest 5. A lesson with no `{paths: ...}` always prints.
   A lesson seen twice (same normalized text, or same file and rule) is offered for promotion: a line in `.harness/checks.sh` (sourced by the Stop hook), a test skeleton in the repo's test directory, or a `review-checklist.md` entry. Record `lives at <path>` on the lesson.
4. Keep the list short: at most 40 lessons. Do not prune yet. List the unpromoted lessons last seen more than 90 days ago (and, past 40, the oldest single-occurrence ones) as the proposed drops.
5. Show the diff of `lessons.md` together with the proposed drops and wait for approval before writing (interactive use). In auto mode, skip the wait; see Auto mode.
5a. Only after approval, run `python3 "$PLUGIN/scripts/dt_gate.py" bridge lessons.py <repo> prune` (`--stale-days N` changes the limit). It drops the unpromoted lessons last seen more than 90 days ago and prints the dropped ids; tell the user which. Past 40, drop the oldest single-occurrence lessons too.
6. After writing, clear the processed entries from the inbox.

## Harness lessons
A candidate whose text starts with `harness:` is about the plugin, not the repo. Do not put it in `lessons.md`. Write it, with the same one-line format and `[H-NNN]` ids, to `.harness/harness-lessons.md` (create it from `$PLUGIN/templates/harness-lessons.md` if absent). `evolve` reads that file and offers each line as a plugin change. These writes follow the same approval rule as step 5.

## Run metrics
After writing lessons in Auto mode, append one line for the run to `.harness/metrics.jsonl`:
`python3 "$PLUGIN/scripts/dt_gate.py" bridge metrics.py <repo> append --stamp <run stamp> --rounds <N> --duration <seconds> --verdict <VERIFIED|...> --agents <a,b> --failures <category=n,...>`
Take rounds, agents, and failure categories from the run's reviewer and verifier files. The plan checkpoint prints the Trend line from this file.

## Auto mode
When `run` invokes this skill after a ship (it does so unless `auto_learn` is `false` in `.claude/dts2-harness.local.md`), skip the approval wait in step 5, write `lessons.md`; do **not** write promotions. List each promotion offer in the returned summary and run `python3 "$PLUGIN/scripts/dt_gate.py" bridge action-items.py <repo> add Promotions "promote L-NNN to <target>"` for each. Append the run's metrics (see Run metrics). Clear the processed inbox entries, and return the `lessons.md` diff for the ship summary. Interactive use keeps the approval wait.

## `learn promote <id>`
Promote one lesson (`L-NNN`) that is already offered: show the exact line or test skeleton and its target (`.harness/checks.sh`, the test directory, or `review-checklist.md`), write it only on an explicit yes, record it with `python3 "$PLUGIN/scripts/dt_gate.py" bridge lessons.py <repo> promote L-NNN --lives-at <path>` (writes `promoted_at: <date>` and `lives at <path>` on the lesson), then run `action-items.py <repo> done <row>` for its Promotions row.

## Regressions
A promoted lesson is held by its check, so session start no longer prints it. When a reviewer or verifier finds the same mistake again after `promoted_at`, run `python3 "$PLUGIN/scripts/dt_gate.py" bridge lessons.py <repo> regress L-NNN`. That raises `regressed: N` on the lesson, which puts it back into the session digest, and the check it lives at needs a fix. `lessons.py <repo> stats` prints `lessons`, `promoted` and `regressed` counts; include the `regressed` count in the ship summary.

## Optional: promote across repos
If the same lesson appears in two or more repos of a workspace, offer to add it to the workspace manifest under `shared_lessons:` so `run` applies it everywhere.

## Guardrails
- Never edit plugin hooks. Promotion writes only to `.harness/checks.sh`, the repo's test directory, or `review-checklist.md`.
- Promotions are written only after an explicit yes.
- Never store secrets, tokens, customer data, or personal details in lessons.
- Never invent a lesson the evidence does not support.
