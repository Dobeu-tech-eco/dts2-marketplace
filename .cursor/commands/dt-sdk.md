---
name: dt-sdk
description: "Cursor name /dt-sdk for the Claude Code command /dt:sdk. Set up and run the dts2 pipeline headless with the Claude Agent SDK (Python) for CI, cron, servers or WSL, with an API key, key command or existing login, plus optional Codex or Gemini review. Use to run the harness head..."
---

# /dt-sdk

Cursor command for the Claude Code command `/dt:sdk`.

This package registers the command so Cursor can show it. It does not run the harness.

Claude Code describes it as: Set up and run the dts2 pipeline headless with the Claude Agent SDK (Python) for CI, cron, servers or WSL, with an API key, key command or existing login, plus optional Codex or Gemini review. Use to run the harness headless, in CI, or with a key.

Do not run a program from a plugin root or a scripts directory. Do not install a package. Do not read a token or a credential file. Do not merge, push to a default branch, force-push, deploy, or delete a branch.

Detailed instructions, when this workspace is the marketplace repo, are in `plugins/dts2-runtime/skills/sdk/SKILL.md`. Those files still name programs this package does not contain. Skip those lines. When a step cannot be done without one, stop and say so.


`sdk` is not in `plugins/dts2-harness`. The runtime tree has the skill. Do not start a headless run and do not read an API key.
