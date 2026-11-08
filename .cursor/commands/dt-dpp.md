---
name: dt-dpp
description: "Cursor name /dt-dpp for the Claude Code command /dt:dpp. Run several autopilot lanes in parallel as headless sons, one worktree each, under a head that plans lanes, supervises, serialises merges and writes one report. Use when the user says dpp, parallel autopilot, or work sev..."
---

# /dt-dpp

Cursor command for the Claude Code command `/dt:dpp`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Run several autopilot lanes in parallel as headless sons, one worktree each, under a head that plans lanes, supervises, serialises merges and writes one report. Use when the user says dpp, parallel autopilot, or work several check-in items at once.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/dpp/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


This command does not pass `--yes`, `--ship`, or an auto-merge flag, and it does not merge.
