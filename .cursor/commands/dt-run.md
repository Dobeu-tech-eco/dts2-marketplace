---
name: dt-run
description: "Cursor name /dt-run for the Claude Code command /dt:run. Run the dts2 plan, build, review, verify pipeline on a task in one repo or workspace: sizes the team, plans against the end state, builds with parallel builders, reviews, ends with a receipt. Use to run the harness or fo..."
---

# /dt-run

Cursor command for the Claude Code command `/dt:run`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Run the dts2 plan, build, review, verify pipeline on a task in one repo or workspace: sizes the team, plans against the end state, builds with parallel builders, reviews, ends with a receipt. Use to run the harness or for a multi-file, cross-repo change.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/run/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


Do not use `/dt-run` as a read-only smoke. The Claude skill's pre-check can install or update files before any build. This command does not pass `--yes`, `--ship`, or an auto-merge flag.
