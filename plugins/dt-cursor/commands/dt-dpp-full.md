---
name: dt-dpp-full
description: "Cursor name /dt-dpp-full for the Claude Code command /dt:dpp-full. dpp with --full. Adds a delegation scan and fills up to five lanes. Outside autopilot it asks before each new lane (dpp_full_ask_each_lane defaults true). Autopilot and fullauto skip that ask. Use when the user..."
---

# /dt-dpp-full

Cursor command for the Claude Code command `/dt:dpp-full`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: dpp with --full. Adds a delegation scan and fills up to five lanes. Outside autopilot it asks before each new lane (dpp_full_ask_each_lane defaults true). Autopilot and fullauto skip that ask. Use when the user says dpp-full or full parallel autopilot.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/dpp-full/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


This command does not pass `--yes`, `--ship`, or an auto-merge flag, and it does not merge.
