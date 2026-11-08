---
name: dt-steer
description: "Cursor name /dt-steer for the Claude Code command /dt:steer. Stop and redirect a run that is in progress. Records the new direction in the intake queue, lets in-flight atomic steps finish, checkpoints, re-plans against the new direction and resumes. Use when the person says st..."
---

# /dt-steer

Cursor command for the Claude Code command `/dt:steer`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Stop and redirect a run that is in progress. Records the new direction in the intake queue, lets in-flight atomic steps finish, checkpoints, re-plans against the new direction and resumes. Use when the person says steer, change direction, or stop and do this instead.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/steer/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.

