---
name: check-in
description: Show project progress against the approved end state as a checklist with N of M complete and a percent, from the Sections map, acceptance boxes and open action items. Read-only. Use when asked for a check-in, progress, status, or what is left, or across every session on the machine (`all`).
---

# Check-in — complete versus outstanding, against the end state

Read-only and runnable any time, mid-run or between runs. It changes no files.

## Steps
1. **Find the project.** Use the repo root (or the workspace root when `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" .` says `workspace-member`). No `.harness/end-state.md` → say `No end state yet; /dt:setup interviews to one.` and stop.
2. **Gather the items the harness already writes; invent no new state format.**
   - The `## Sections` table and the `## Acceptance criteria` boxes in `.harness/end-state.md`: a section is complete when its status is `done` (`todo`, `in-progress` and `blocked` are outstanding); an acceptance box is complete when it is `[x]`.
   - Open items from `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/action-items.py" <repo> list` (secrets, decisions, handoffs, deploy steps): each open one is outstanding, named `<id> <group>: <item>`.
3. **Summarize and render.** Either pass the whole end state to the script, `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/check-in.py" --from .harness/end-state.md`, or, when you also gathered action items, pass everything as one list: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/check-in.py" --items '[{"name":"section 1: data model","status":"complete"},{"name":"A1 Secrets: STRIPE_KEY","status":"outstanding"}]'`. Add `--json` for the raw summary (`total`, `complete`, `outstanding`, `percent`, `complete_items`, `outstanding_items`).
4. **Show it** exactly as the script prints it: a header `N of M complete (P%)`, then `[x]` for each complete item and `[ ]` for each outstanding one. Then add one line naming the next outstanding item and the command that moves it (`/dt:run <task>`, `/dt:action-items`, `/dt:run resume`, or `/dt:autopilot resume`).
5. **Autopilot.** When `.harness/autopilot/latest.md` exists, print its header line and progress table as written (step, branch, plan vote, build vote, council, PR, CI, merged, status), then one line: `Autopilot <stamp>: <done> of <total> steps done, <parked> parked, current: <first step not done or parked>`. For each step that went to council, add one line with its tally, the head's decision and the path to `.harness/autopilot/council-<stamp>-<step>.md`, so the user can read why. A status of `stopped` adds `resume with /dt:autopilot resume`. Section statuses in the checklist above already reflect merged steps, because autopilot sets them to `done` after each merge.
6. **All sessions on this machine.** When invoked as `/dt:check-in all`, or the user asks for every session or all harnesses, run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/fleet.py" checkins [--since 24h] [--json]` and show its report, leading with "Needs you" (blockers and questions). Then offer, and confirm first, `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/fleet.py" broadcast --kind checkin --to all` to ask every live session for a fresh check-in; re-run `checkins` a few minutes later. A session answers with `fleet.py checkin --session <id> --status "<one line, free text>" [--blocker X ...] [--next N] [--question Q ...]`. Sessions answer on their next prompt, tool call or stop; one idle at the prompt answers only when next touched.

## Notes
- An empty list prints `0 of 0 complete (0%)`; it never errors on a project with no items yet.
- This skill reports; it never marks anything done. `run` updates section statuses and acceptance boxes at ship.
