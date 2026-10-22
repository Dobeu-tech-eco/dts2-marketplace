---
name: check-in
description: Show where the project stands, from where it started through the approved end state, as a checklist with every item marked complete or outstanding. Reads the Sections map and acceptance boxes in the end state plus open action items, then prints a header with N of M complete and a percent. Runnable any time, read-only. Use when the user asks for a check-in, progress, status, what is done, what is left, or how far along the project is.
---

# Check-in — complete versus outstanding, against the end state

Read-only and runnable any time, mid-run or between runs. It changes no files.

## Steps
1. **Find the project.** Use the repo root (or the workspace root when `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" .` says `workspace-member`). No `.harness/end-state.md` → say `No end state yet; /dts2-harness:setup interviews to one.` and stop.
2. **Gather the items the harness already writes; invent no new state format.**
   - The `## Sections` table and the `## Acceptance criteria` boxes in `.harness/end-state.md`: a section is complete when its status is `done` (`todo`, `in-progress` and `blocked` are outstanding); an acceptance box is complete when it is `[x]`.
   - Open items from `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/action-items.py" <repo> list` (secrets, decisions, handoffs, deploy steps): each open one is outstanding, named `<id> <group>: <item>`.
3. **Summarize and render.** Either pass the whole end state to the script, `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/check-in.py" --from .harness/end-state.md`, or, when you also gathered action items, pass everything as one list: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/check-in.py" --items '[{"name":"section 1: data model","status":"complete"},{"name":"A1 Secrets: STRIPE_KEY","status":"outstanding"}]'`. Add `--json` for the raw summary (`total`, `complete`, `outstanding`, `percent`, `complete_items`, `outstanding_items`).
4. **Show it** exactly as the script prints it: a header `N of M complete (P%)`, then `[x]` for each complete item and `[ ]` for each outstanding one. Then add one line naming the next outstanding item and the command that moves it (`/dts2-harness:run <task>`, `/dts2-harness:action-items`, or `/dts2-harness:run resume`).

## Notes
- An empty list prints `0 of 0 complete (0%)`; it never errors on a project with no items yet.
- This skill reports; it never marks anything done. `run` updates section statuses and acceptance boxes at ship.
