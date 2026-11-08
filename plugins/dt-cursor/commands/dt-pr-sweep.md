---
name: dt-pr-sweep
description: "Cursor name /dt-pr-sweep for the Claude Code command /dt:pr-sweep. Clear open and stale PRs in one pass with parallel workers: merge green ones, rebase, triage red CI, close dead ones, optionally speed up CI. Use for clean up open PRs, stale PRs, or after an autopilot run."
---

# /dt-pr-sweep

Cursor command for the Claude Code command `/dt:pr-sweep`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Clear open and stale PRs in one pass with parallel workers: merge green ones, rebase, triage red CI, close dead ones, optionally speed up CI. Use for clean up open PRs, stale PRs, or after an autopilot run.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/pr-sweep/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


The instruction edition's execute phase merges pull requests. This command does not merge, close, or delete branches.
