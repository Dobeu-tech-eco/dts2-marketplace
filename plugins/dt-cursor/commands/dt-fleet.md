---
name: dt-fleet
description: "Cursor name /dt-fleet for the Claude Code command /dt:fleet. See every harness session on this computer, read their status, logs and ledgers without interrupting them, and send one note, handoff, pause or knowledge finding to all of them. Use for list my sessions, what are all..."
---

# /dt-fleet

Cursor command for the Claude Code command `/dt:fleet`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: See every harness session on this computer, read their status, logs and ledgers without interrupting them, and send one note, handoff, pause or knowledge finding to all of them. Use for list my sessions, what are all my harnesses doing, tell every session to hand off, or broadcast to all agents.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/fleet/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


The Claude description is limited to sessions on one computer. It is not a list of every computer, and it is not proof of two side-by-side windows. This command does not discover or message sessions.
