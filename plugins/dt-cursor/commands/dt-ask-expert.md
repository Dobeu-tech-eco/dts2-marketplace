---
name: dt-ask-expert
description: "Cursor name /dt-ask-expert for the Claude Code command /dt:ask-expert. Ask an expert panel whether to keep, fold, sell as a template, archive or delete one repo. Reads the code, checks your goal, votes across three model providers, and writes a one-page decision memo. Use for..."
---

# /dt-ask-expert

Cursor command for the Claude Code command `/dt:ask-expert`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Ask an expert panel whether to keep, fold, sell as a template, archive or delete one repo. Reads the code, checks your goal, votes across three model providers, and writes a one-page decision memo. Use for should I keep this repo or what do I do with this project.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-harness/skills/ask-expert/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.

