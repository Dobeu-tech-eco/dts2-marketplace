---
name: dt-evolve
description: "Cursor name /dt-evolve for the Claude Code command /dt:evolve. Change the dts2 harness itself in its source repo: edit a skill, agent, hook, script, profile or template, validate, test, bump versions, commit; push only on an explicit yes. Use for evolve, improve the harness, o..."
---

# /dt-evolve

Cursor command for the Claude Code command `/dt:evolve`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Change the dts2 harness itself in its source repo: edit a skill, agent, hook, script, profile or template, validate, test, bump versions, commit; push only on an explicit yes. Use for evolve, improve the harness, or fix a dts2 skill.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/evolve/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.

