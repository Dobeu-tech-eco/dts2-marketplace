---
name: dt-ship
description: "Cursor name /dt-ship for the Claude Code command /dt:ship. Ship the current branch as a pull request: pre-check, repo checks, secret scan, verifier and reviewer, receipt, PR template, push, open PR; then sweep stale branches and PRs after one confirmation. Never merges. Use fo..."
---

# /dt-ship

Cursor command for the Claude Code command `/dt:ship`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Ship the current branch as a pull request: pre-check, repo checks, secret scan, verifier and reviewer, receipt, PR template, push, open PR; then sweep stale branches and PRs after one confirmation. Never merges. Use for ship, open a PR, or clean up PRs.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/ship/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


This command does not pass `--yes`, `--ship`, or an auto-merge flag, and it does not merge.
