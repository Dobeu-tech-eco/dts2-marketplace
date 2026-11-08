---
name: dt-learn
description: "Cursor name /dt-learn for the Claude Code command /dt:learn. Consolidate reviewer and verifier findings into durable per-repo lessons in .harness/lessons.md that future runs read, and prune stale ones. Use after runs, or for learn from this, learn promote L-NNN, remember this..."
---

# /dt-learn

Cursor command for the Claude Code command `/dt:learn`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Consolidate reviewer and verifier findings into durable per-repo lessons in .harness/lessons.md that future runs read, and prune stale ones. Use after runs, or for learn from this, learn promote L-NNN, remember this mistake, or update lessons.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/learn/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.

