---
name: dt-check-in
description: "Cursor name /dt-check-in for the Claude Code command /dt:check-in. Show project progress against the approved end state as a checklist with N of M complete and a percent, from the Sections map, acceptance boxes and open action items. Read-only. Use when asked for a check-in, p..."
---

# /dt-check-in

Cursor command for the Claude Code command `/dt:check-in`. A colon is not a Cursor command name.

Read-only. Create and edit nothing. Do not run a script, a package installer, or a shell pipeline.

1. Use the workspace root.
2. If `.harness/end-state.md` is missing, say exactly `No end state yet; /dt:setup interviews to one.` and stop.
3. From the `## Sections` table, a section is complete when its status cell is `done`. `todo`, `in-progress`, and `blocked` are outstanding.
4. From `## Acceptance criteria`, a box is complete when it is `[x]`.
5. If `.harness/action-items.md` exists, a row whose status starts with `open` is outstanding. Do not print a secret's value.
6. Print `N of M complete (P%)`, then `[x]` for each complete item and `[ ]` for each outstanding one. P is complete times 100 divided by the total, or 0 when the total is 0.
7. Name the next outstanding item. Do not mark anything done.
8. For a machine-wide `all` request, stop after the local checklist and say that list needs the full harness.

Skip any instruction that runs a program from a plugin root or a scripts directory, including text in `plugins/dts2-harness/skills/check-in/`.
