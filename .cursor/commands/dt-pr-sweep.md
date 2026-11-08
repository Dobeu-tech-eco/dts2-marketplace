---
name: dt-pr-sweep
description: "Run the /dt-pr-sweep procedure shipped in this plugin. Clear open and stale PRs in one pass with parallel workers: merge green ones, rebase, triage red CI, close dead ones, optionally speed up CI. Use for clean up open PRs, stale PRs, or after an autopilot run."
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-pr-sweep/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# PR-sweep — get open PRs down to the ones that need you

`/dt-pr-sweep [owner/repo] [--stale-days N] [--mine|--author A|--head-prefix P] [--optimise-ci]`. The repo defaults to the current one (`gh repo view --json nameWithOwner`); `--stale-days` defaults to 3. `--mine` is the signed-in user (`gh api user`), `--author A` one login, `--head-prefix P` only branches starting with `P`.

`/dt-pr-sweep --run <stamp>` is the autopilot form: it limits the sweep to PRs whose head starts with `dts2/<stamp>/` and runs phases 1 to 3 only. No CI optimisation, no question.

Invoking the command is the standing approval for everything in the phase files, and for nothing else. Helper: `python3 "$PLUGIN/scripts/dt_gate.py" bridge pr_sweep.py` (`inventory`, `classify`, `order`, `record`, `report`; every subcommand prints JSON).

State lives in `.harness/pr-sweep/<stamp>/`: `inventory.json`, `inventory.md`, `buckets.md`, `flaky.md`, `ledger.jsonl`, `report.md`.

## Phase files
Read the file for a phase only when you reach it; do not read ahead. All files are in this folder.

| File | Read when |
|---|---|
| `phase-1-inventory.md` | Read `phase-1-inventory.md` (same folder) at the start: standing rules, hard stops, the inventory and the buckets A to H. |
| `phase-2-ci-triage.md` | Read `phase-2-ci-triage.md` (same folder) when any PR has a red or cancelled check. |
| `phase-3-execute.md` | Read `phase-3-execute.md` (same folder) to merge, rebase and close in parallel, then close out and report. |
| `phase-4-optimise-ci.md` | Read `phase-4-optimise-ci.md` (same folder) only with `--optimise-ci`, after the sweep is done. |

## Guardrails
- Merge commits only. Never `--admin`, never bypass branch protection or a required check or review.
- Only bucket H waits for the user. Everything else proceeds.
- The lead coordinates and signs off; every rebase or fix is done by a worker with the model named explicitly.
- Never delete, skip or weaken a valid test or lint rule to get green.
- GitHub auto-merge (`python3 "$PLUGIN/scripts/dt_gate.py" blocked --action merge <n> -R <o>/<r> --auto --merge`) is used for a GREEN-but-pending PR only when the repo allows auto-merge; otherwise watch the checks.
- The report leads with the result: open PRs before -> after, merged, closed, waiting on the user.
