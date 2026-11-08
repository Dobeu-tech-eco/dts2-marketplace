---
name: dt-setup
description: "Cursor name /dt-setup for the Claude Code command /dt:setup. Interview the user to an approved end state (.harness/end-state.md), then scaffold dts2 config in one repo, many repos or a workspace. Use to set up, init or configure the harness, run the interview, or revise the en..."
---

# /dt-setup

Cursor command for the Claude Code command `/dt:setup`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Interview the user to an approved end state (.harness/end-state.md), then scaffold dts2 config in one repo, many repos or a workspace. Use to set up, init or configure the harness, run the interview, or revise the end state. --scaffold-only skips it.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/setup/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.

