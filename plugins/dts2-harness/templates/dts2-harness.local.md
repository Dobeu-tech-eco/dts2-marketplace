---
enabled: true
# Hooks
stop_checks: true
stop_checks_block: false     # true = a red typecheck, lint or checks.sh run blocks the stop once (never twice in a row)
lessons_inject: true
lessons_max: 5
pr_receipt_template_push: false  # true = the PR-receipt hook commits and pushes the PR template to the PR branch (never in son mode)
# Team scaling for the run skill
auto_scale: true
max_builders: 4
max_reviewers: 4
continuous_dispatch: true     # keep max_builders in flight while ready sections exist; park stalled builders and move on
builder_timeout_min: 20       # minutes without a builder report before it is parked
son_permission_mode: dontAsk   # claude -p permission mode for dpp sons: dontAsk | acceptEdits | plan | default (bypassPermissions is refused; tool allowlist, deny list and guard hook apply); sons commit only, the head pushes
mailbox_wait_min: 30           # minutes a son waits for the head's answer or a merge-go before it parks as incomplete (mailbox-timeout)
dpp_full_ask_each_lane: true   # dpp-full outside autopilot asks the user before each new lane is leased
fullauto_freeze_scope: true    # fullauto freezes the approved item set at its first plan; new check-in items wait in a pending list
son_model: opus            # model every dpp son runs on (alias or full model id)
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
context_guard_stop: false        # true = the guard also ends the turn (continue:false) instead of only advising
# Delegation (Rule 9): frontier is for advice and sign-off only; builders never run a frontier model
max_execution_effort: high   # cap builder effort (low|medium|high|max); the lead never gives a builder a frontier model
delegation_strict: true   # block ship if any builder ran a frontier model
lead_provider: claude   # agent that fills the lead/advisory/sign-off seats; execution still uses the cheapest capable per delegate.py
# tokenBurn and effortLevels in profiles/agents/*.json are relative, user-editable weights, NOT prices or quotas: tokenBurn only ranks agents for a seat (lower = cheaper to run).
# Human approvals (merge, lane_override, ...) are not set here: add {"dts2_approvals": {"merge": ["<pr>"]}} to .claude/settings.local.json yourself; no son can write that file
# roster: see .harness/config.yaml (agent roster lives there, not here)
# budget, supervisor: run caps, call limit, stall_minutes and fallback model for dpp live in .harness/config.yaml (see templates/config-supervisor.yaml)
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
