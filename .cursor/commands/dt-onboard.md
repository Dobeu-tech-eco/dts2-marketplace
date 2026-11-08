---
name: dt-onboard
description: "Cursor name /dt-onboard for the Claude Code command /dt:onboard. Explain the dts2 harness (eight agents, twenty-seven skills, roster, team tiers, lessons, headless runner) and recommend where to start. Use when the user asks what dts2 does, how to use it, which skill fits a jo..."
---

# /dt-onboard

Cursor command for the Claude Code command `/dt:onboard`. Explain only. Write nothing. Do not scan the machine, install a plugin, or copy skills into another tool.

DT: Init to Ship Auto Agent Orchestrator is a Dobeu Tech Solutions LLC product. MIT. https://dobeu.net

In Claude Code the plugin name `dt` prefixes each skill, so the commands are `/dt:<skill>`. In Cursor those actions are `/dt-<skill>`, plus the index skill `/dt`. Typing the colon form does not select these files.

This package can explain the roles and run the read-only commands `/dt-check-in` and `/dt-action-items`. Planning, building, shipping, merging, and unattended loops stay in the full harness (`plugins/dts2-runtime`, GitHub marketplace `dt@dts2`). This package does not start those.

Roles: scout, lead, builder, reviewer, verifier, fixer, auditor, incident-reviewer. The builder does not review its own work. A checkpoint asks for approve, edit, or stop.

Commands:

- `/dt-action-items` for Claude Code `/dt:action-items`
- `/dt-ask-expert` for Claude Code `/dt:ask-expert`
- `/dt-autopilot` for Claude Code `/dt:autopilot`
- `/dt-check-in` for Claude Code `/dt:check-in`
- `/dt-composio` for Claude Code `/dt:composio`
- `/dt-cooldown` for Claude Code `/dt:cooldown`
- `/dt-dpp` for Claude Code `/dt:dpp`
- `/dt-dpp-full` for Claude Code `/dt:dpp-full`
- `/dt-evolve` for Claude Code `/dt:evolve`
- `/dt-feature` for Claude Code `/dt:feature`
- `/dt-find-skills` for Claude Code `/dt:find-skills`
- `/dt-fleet` for Claude Code `/dt:fleet`
- `/dt-fullauto` for Claude Code `/dt:fullauto`
- `/dt-gtm` for Claude Code `/dt:gtm`
- `/dt-incidents` for Claude Code `/dt:incidents`
- `/dt-knowledge` for Claude Code `/dt:knowledge`
- `/dt-learn` for Claude Code `/dt:learn`
- `/dt-machine-prep` for Claude Code `/dt:machine-prep`
- `/dt-model` for Claude Code `/dt:model`
- `/dt-onboard` for Claude Code `/dt:onboard`
- `/dt-pr-sweep` for Claude Code `/dt:pr-sweep`
- `/dt-repo-sweep` for Claude Code `/dt:repo-sweep`
- `/dt-run` for Claude Code `/dt:run`
- `/dt-sdk` for Claude Code `/dt:sdk`
- `/dt-setup` for Claude Code `/dt:setup`
- `/dt-ship` for Claude Code `/dt:ship`
- `/dt-steer` for Claude Code `/dt:steer`

Start with `/dt-check-in`. It reads `.harness/end-state.md` and writes nothing.
