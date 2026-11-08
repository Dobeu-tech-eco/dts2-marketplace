---
name: dt-cooldown
description: "Cursor name /dt-cooldown for the Claude Code command /dt:cooldown. Pause an agent that hit a usage limit until its reset date, resume it, or list what is paused. Use for set a cooldown, agent is out of usage, clear a cooldown, or which agents are paused."
---

# /dt-cooldown

Cursor command for the Claude Code command `/dt:cooldown`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Pause an agent that hit a usage limit until its reset date, resume it, or list what is paused. Use for set a cooldown, agent is out of usage, clear a cooldown, or which agents are paused.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/cooldown/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.

