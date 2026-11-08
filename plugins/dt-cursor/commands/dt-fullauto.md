---
name: dt-fullauto
description: "Cursor name /dt-fullauto for the Claude Code command /dt:fullauto. dpp-full with autopilot forced on, looping until a check-in reports nothing outstanding. Use when the user says fullauto, run everything, or finish the end state unattended."
---

# /dt-fullauto

Cursor command for the Claude Code command `/dt:fullauto`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: dpp-full with autopilot forced on, looping until a check-in reports nothing outstanding. Use when the user says fullauto, run everything, or finish the end state unattended.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/fullauto/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


This command does not pass `--yes`, `--ship`, or an auto-merge flag, and it does not merge.
