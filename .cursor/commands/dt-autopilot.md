---
name: dt-autopilot
description: "Cursor name /dt-autopilot for the Claude Code command /dt:autopilot. Run harness steps end to end without human plan or ship approval: a gate of three frontier models from different providers and a council for deadlocks replace the checkpoints. One branch and PR per step. Use..."
---

# /dt-autopilot

Cursor command for the Claude Code command `/dt:autopilot`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Run harness steps end to end without human plan or ship approval: a gate of three frontier models from different providers and a council for deadlocks replace the checkpoints. One branch and PR per step. Use for autopilot or run unattended.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/autopilot/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


This command does not pass `--yes`, `--ship`, or an auto-merge flag, and it does not merge.
