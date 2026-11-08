---
name: dt
description: "Index of DT harness commands in Cursor. Use only when the user invokes /dt or asks for a /dt: harness command. Runs nothing by itself."
disable-model-invocation: true
---

# dt

Index for the DT harness in Cursor. Dobeu Tech Solutions LLC. MIT.

Claude Code discovers these actions as `/dt:<skill>` because the plugin name is `dt`. Cursor discovers `/dt` (this skill) and `/dt-<skill>` (one file per action). A colon is not part of the Cursor name.

Invoke a command only when the user asks for it. `/dt-check-in`, `/dt-onboard`, and `/dt-action-items` are read-only. Every other `/dt-<skill>` file tells you to stop before scripts, installs, merges, and deploys.

- `/dt-action-items` (Claude Code `/dt:action-items`)
- `/dt-ask-expert` (Claude Code `/dt:ask-expert`)
- `/dt-autopilot` (Claude Code `/dt:autopilot`)
- `/dt-check-in` (Claude Code `/dt:check-in`)
- `/dt-composio` (Claude Code `/dt:composio`)
- `/dt-cooldown` (Claude Code `/dt:cooldown`)
- `/dt-dpp` (Claude Code `/dt:dpp`)
- `/dt-dpp-full` (Claude Code `/dt:dpp-full`)
- `/dt-evolve` (Claude Code `/dt:evolve`)
- `/dt-feature` (Claude Code `/dt:feature`)
- `/dt-find-skills` (Claude Code `/dt:find-skills`)
- `/dt-fleet` (Claude Code `/dt:fleet`)
- `/dt-fullauto` (Claude Code `/dt:fullauto`)
- `/dt-gtm` (Claude Code `/dt:gtm`)
- `/dt-incidents` (Claude Code `/dt:incidents`)
- `/dt-knowledge` (Claude Code `/dt:knowledge`)
- `/dt-learn` (Claude Code `/dt:learn`)
- `/dt-machine-prep` (Claude Code `/dt:machine-prep`)
- `/dt-model` (Claude Code `/dt:model`)
- `/dt-onboard` (Claude Code `/dt:onboard`)
- `/dt-pr-sweep` (Claude Code `/dt:pr-sweep`)
- `/dt-repo-sweep` (Claude Code `/dt:repo-sweep`)
- `/dt-run` (Claude Code `/dt:run`)
- `/dt-sdk` (Claude Code `/dt:sdk`)
- `/dt-setup` (Claude Code `/dt:setup`)
- `/dt-ship` (Claude Code `/dt:ship`)
- `/dt-steer` (Claude Code `/dt:steer`)

Files under `plugins/dts2-harness/skills/` are the Claude instruction edition. They are not loaded as Cursor skills. Loading them would publish names such as `sdk` and `autopilot`, which already belong to Cursor, and those files name programs this package does not contain.
