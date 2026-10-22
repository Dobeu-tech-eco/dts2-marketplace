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
continuous_dispatch: true     # keep max_builders in flight while ready sections exist; park stalled builders and move on
builder_timeout_min: 20       # minutes without a builder report before it is parked
use_worktrees: auto        # auto = one worktree per builder in a git repo (scratch dir per builder without git) | always | never
# Headless runner (sdk skill)
second_opinion: none       # none | codex | gemini
# Machine prep
profile: blueprint         # file name under the plugin's profiles/ folder, or a path
# End-state clarity gate
end_state_threshold: 80
# Learning
auto_learn: true          # run learn after the ship checkpoint; false turns it off
# Context guard (PostToolUse hook)
context_guard: true              # stop the run and re-run setup on a context spike before the plan checkpoint, or when run from a workspace member folder
context_guard_tool_calls: 250    # tool calls in this session before the guard fires
context_guard_mb: 12             # transcript size in MB before the guard fires
# Delegation (Rule 9): frontier is for advice and sign-off only; builders never run a frontier model
max_execution_effort: high   # cap builder effort (low|medium|high|max); the lead never gives a builder a frontier model
delegation_strict: true   # block ship if any builder ran a frontier model
lead_provider: claude   # agent that fills the lead/advisory/sign-off seats; execution still uses the cheapest capable per delegate.py
# tokenBurn and effortLevels in profiles/agents/*.json are relative, user-editable weights, NOT prices or quotas: tokenBurn only ranks agents for a seat (lower = cheaper to run).
# roster: see .harness/config.yaml (agent roster lives there, not here)
# dev_server: command to start the app for walkthrough review, set in .harness/config.yaml
---

# dts2-harness settings for this project

Per-project overrides. This file is not committed (`.claude/*.local.md` is gitignored by the setup skill).
Restart Claude Code after editing so hooks pick up changes.
# Agent CLI locations (roster)
# If an agent CLI is installed but off PATH, point the harness at it without editing profiles:
#   export DTS2_BIN_AGY=/full/path/to/agy      # Gemini via the Antigravity CLI
#   export DTS2_BIN_GROK=/full/path/to/grok
# The value may be the binary itself or the folder holding it. Or add the folder to the
# agent profile's "searchPaths". Gemini's binary is "agy" (Antigravity), not "gemini".
