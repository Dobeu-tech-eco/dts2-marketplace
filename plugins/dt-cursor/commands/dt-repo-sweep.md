---
name: dt-repo-sweep
description: "Cursor name /dt-repo-sweep for the Claude Code command /dt:repo-sweep. Review every repo of a GitHub owner, oldest first, with a quick expert pass each, then clean up from one screen: keep, fold, sell as template, archive. Deleting is one repo at a time, with a backup. Use for..."
---

# /dt-repo-sweep

Cursor command for the Claude Code command `/dt:repo-sweep`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Review every repo of a GitHub owner, oldest first, with a quick expert pass each, then clean up from one screen: keep, fold, sell as template, archive. Deleting is one repo at a time, with a backup. Use for clean up my repos or sweep my old projects.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/repo-sweep/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.

