---
name: fullauto
description: dpp-full with autopilot forced on, looping until a check-in reports nothing outstanding. Use when the user says fullauto, run everything, or finish the end state unattended.
disable-model-invocation: true
---

# fullauto — dpp-full under autopilot, to the end

Run `skills/dpp/SKILL.md` as dpp-full with autopilot on for every lane; the head re-runs `/dts2:check-in` after each son reports `done` or `incomplete` and before the next dispatch, so new items join the candidates. Each pass first runs `lanes.py loop <stamp>`; when it returns `stop: true` (`max_fullauto_loops` reached) the run parks as `incomplete` with the ledger written and the final report lists what is left.
Plan with `--full --fullauto --autopilot` (dpp section 5.5): under `fullauto_freeze_scope: true` the item set approved at the first plan is frozen and new check-in items wait in the pending list. Stop when `lanes.py stop-check <stamp> --from-checkin <check-in.json> --base <branch>` (the end state read from the fetched `origin/<branch>`; items tied to a ledgered blocked PR do not count as outstanding) says a check-in run found nothing outstanding, with each lane `done`, or `blocked` and listed in the task ledger (autopilot §5a).
Every pass also follows dpp §5 and §6: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py" reconcile <stamp>` before a PR is created, merged or a lane resumed, and `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py" transition` for every phase move. When the loop stops, for any reason, end with `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py" shutdown <stamp>` and print `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py" report <stamp>`.
Stop early only on an autopilot §4 hard stop or a lane the council could not clear (autopilot §1b); the final report then lists the remaining items.
