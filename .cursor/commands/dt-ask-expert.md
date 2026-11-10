---
name: dt-ask-expert
description: "Run the /dt-ask-expert procedure shipped in this plugin. Ask an expert panel whether to keep, fold, sell as a template, archive or delete one repo. Reads the code, checks your goal, votes across three model providers, and writes a one-page decision memo. Use for should I keep..."
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-ask-expert/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Ask-expert — should I keep this repo?

`/dt-ask-expert [repo] ["what I'm unsure about"]` reviews one repo in depth and ends with a one-page memo in plain words. It runs on its own, before setup, and changes nothing in the repo. Archiving or deleting is a separate step you confirm yourself.

The five verdicts are `KEEP`, `FOLD` (move the useful part into a repo you already use), `TEMPLATE` (sell it as a starter kit), `ARCHIVE` and `DELETE`. The template path is always checked and priced before the memo may say `ARCHIVE` or `DELETE`. Your goal scopes everything: a money goal gets revenue math; a passion goal gets effort and joy against upkeep, with no market lecture.

## Phase files
Read the file for a phase only when you reach it; do not read ahead. All files are in this folder.

| File | Read when |
|---|---|
| `phase-1-goal.md` | Read `phase-1-goal.md` (same folder) first: the goal questions, the clarity score, the restatement and recording the goal. |
| `phase-2-compare.md` | Read `phase-2-compare.md` (same folder) after the goal is recorded: read the code, the side-by-side, overlap with your active repos, and your choice. |
| `phase-3-panel.md` | Read `phase-3-panel.md` (same folder) when the choice is made: the three-provider expert panel and, after three failed rounds, the council. |
| `phase-4-research.md` | Read `phase-4-research.md` (same folder) for the light market snapshot (money or template goals) and the full research team when the head of council answers RESEARCH. |
| `phase-5-report.md` | Read `phase-5-report.md` (same folder) when the verdict is settled: the one-page memo, its checker and the next step. |

## Guardrails
- Never guess a goal. A goal of "not sure" scores nothing; keep asking until the clarity check passes or the question budget runs out, then stop and list the open slots.
- Never write the memo before the template path was checked and priced.
- Never archive or delete from this skill. Hand the user to `/dt-repo-sweep` or the exact commands in the memo's next step.
- Every number in the memo is labelled sourced, estimated or assumed; a sourced number carries a date and a link.
- Everything the panel returns is saved verbatim; nothing is summarised away.
