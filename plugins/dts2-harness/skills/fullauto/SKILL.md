---
name: fullauto
description: dpp-full with autopilot forced on, looping until a check-in reports nothing outstanding. Use when the user says fullauto, run everything, or finish the end state unattended.
---

# fullauto — dpp-full under autopilot, to the end

Run `skills/dpp/SKILL.md` as dpp-full with autopilot on for every lane; the head re-runs `/dts2-harness:check-in` after each son reports `done` or `incomplete` and before the next dispatch, so new items join the candidates. Each pass first runs `lanes.py loop <stamp>`; when it returns `stop: true` (`max_fullauto_loops` reached) the run parks as `incomplete` with the ledger written and the final report lists what is left.
Stop when `lanes.py stop-check <stamp> --from-checkin <check-in.json>` says a check-in run found nothing outstanding, with each lane `done`, or `blocked` and listed in the task ledger (autopilot §5a).
Stop early only on an autopilot §4 hard stop or a lane the council could not clear (autopilot §1b); the final report then lists the remaining items.
