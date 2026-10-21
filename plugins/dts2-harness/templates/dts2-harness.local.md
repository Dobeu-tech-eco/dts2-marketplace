---
enabled: true
# Hooks
stop_checks: true
lessons_inject: true
lessons_max: 10
# Team scaling for the run skill
auto_scale: true
max_builders: 6
max_reviewers: 4
use_worktrees: auto        # auto | always | never
# Headless runner (sdk skill)
second_opinion: none       # none | codex | gemini
# Machine prep
profile: blueprint         # file name under the plugin's profiles/ folder, or a path
# End-state clarity gate
end_state_threshold: 80
# Learning
auto_learn: true          # run learn after the ship checkpoint; false turns it off
# roster: see .harness/config.yaml (agent roster lives there, not here)
# dev_server: command to start the app for walkthrough review, set in .harness/config.yaml
---

# dts2-harness settings for this project

Per-project overrides. This file is not committed (`.claude/*.local.md` is gitignored by the setup skill).
Restart Claude Code after editing so hooks pick up changes.
