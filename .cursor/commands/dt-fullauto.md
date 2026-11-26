---
name: dt-fullauto
description: "Run the /dt-fullauto procedure shipped in this plugin. dpp-full with autopilot forced on, looping until a check-in reports nothing outstanding. Use when the user says fullauto, run everything, or finish the end state unattended."
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-fullauto/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# fullauto — dpp-full under autopilot, to the end

Run `skills/dpp/SKILL.md` as dpp-full with autopilot on for every lane; the head re-runs `/dt-check-in` after each son reports `done` or `incomplete` and before the next dispatch, so new items join the candidates. Each pass first runs `lanes.py loop <stamp>`; when it returns `stop: true` (`max_fullauto_loops` reached) the run parks as `incomplete` with the ledger written and the final report lists what is left.
Plan with `--full --fullauto --autopilot` (dpp section 5.5): under `fullauto_freeze_scope: true` the item set approved at the first plan is frozen and new check-in items wait in the pending list. Stop when `lanes.py stop-check <stamp> --from-checkin <check-in.json> --base <branch>` (the end state read from the fetched `origin/<branch>`; items tied to a ledgered blocked PR do not count as outstanding) says a check-in run found nothing outstanding, with each lane `done`, or `blocked` and listed in the task ledger (autopilot §5a).
Every pass also follows dpp §5 and §6: `python3 "$PLUGIN/scripts/dt_gate.py" bridge lanes.py reconcile <stamp>` before a PR is created, merged or a lane resumed, and `python3 "$PLUGIN/scripts/dt_gate.py" bridge lanes.py transition` for every phase move. When the loop stops, for any reason, end with `python3 "$PLUGIN/scripts/dt_gate.py" bridge lanes.py shutdown <stamp>` and print `python3 "$PLUGIN/scripts/dt_gate.py" bridge lanes.py report <stamp>`.
Stop early only on an autopilot §4 hard stop or a lane the council could not clear (autopilot §1b); the final report then lists the remaining items. Unattended outer loop (`autonomy: unattended` in `.harness/config.yaml` lifts the `max_fullauto_loops` cap; `max_fullauto_loops: 3` stays the default): set `/goal` to "all ready items are done or parked, or loop_guard.py returned a stall verdict or STOP" and run `/loop` over `.claude/loop.md`, copied from `templates/loop.md`. Each pass runs `python3 "$PLUGIN/scripts/dt_gate.py" bridge loop_guard.py check` (exit 2 prints STOP), then `loop_guard.py sweep --release`, picks the next ready item, does it as one round, `loop_guard.py park`s an item that needs a person, and ends with `loop_guard.py record --progress "<open items> | <merged PRs>" --signature "<failure>"`. A `stall` verdict (no progress for `loop.no_progress_limit` passes, or one failure signature three times in a row) or a `stop` runs `loop_guard.py notify`, which opens or updates the one "dts2: needs you" issue and writes a local note, then the run ends with the `shutdown` and `report` steps above; merge and policy rules are unchanged.
