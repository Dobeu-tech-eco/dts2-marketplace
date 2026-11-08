---
name: dt-machine-prep
description: "Cursor name /dt-machine-prep for the Claude Code command /dt:machine-prep. Scan this computer's agent tooling (plugins, agents, skills, CLAUDE.md, Codex, Cursor, MCP servers), compare to the blueprint profile, prune by disabling, and set up the slim startup. Use to clean up pl..."
---

# /dt-machine-prep

Cursor command for the Claude Code command `/dt:machine-prep`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Scan this computer's agent tooling (plugins, agents, skills, CLAUDE.md, Codex, Cursor, MCP servers), compare to the blueprint profile, prune by disabling, and set up the slim startup. Use to clean up plugins, audit context budget, or set up a machine.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/machine-prep/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.

