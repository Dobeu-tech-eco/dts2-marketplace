---
name: dt-find-skills
description: "Cursor name /dt-find-skills for the Claude Code command /dt:find-skills. Rescan the repo, audit every improvement option (skills, database tooling, hooks, MCP servers, plugins, commands, subagents, permissions, CI, docs), ask one to three questions, recommend a ranked set, and..."
---

# /dt-find-skills

Cursor command for the Claude Code command `/dt:find-skills`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Rescan the repo, audit every improvement option (skills, database tooling, hooks, MCP servers, plugins, commands, subagents, permissions, CI, docs), ask one to three questions, recommend a ranked set, and wire in the picks on a yes. Use when the user says find skills or how can I improve this setup.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/find-skills/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.

