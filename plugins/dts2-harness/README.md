# dts2-harness

Second-generation Dobeu Tech Solutions agent harness. It supersedes `harness@harness` (plugin-claudeharness) and `harness-ops`. Enable dts2 and disable those two so each agent exists once.

## What it adds over v1
| Need | How dts2 handles it |
|---|---|
| WSL and Linux | Python core scripts, bash hooks, PowerShell and bash installers. `env-detect.py` finds which Claude home is live, including the WSL wrapper that runs Windows `claude.exe`. |
| Scan, prune, set up a machine | `machine-prep` skill plus `auditor` agent and `scripts/machine-prep.py` (audit, plan, apply) driven by `profiles/blueprint.json` from agent-startup-blueprint. Prune means disable, with a settings backup first. |
| Many repos | `setup` skill in batch mode (one subagent per repo, in parallel) or workspace mode (`.harness-workspace.yaml` with contracts and release order). |
| Self-learning | `learn` skill keeps `.harness/lessons.md`. The SessionStart hook loads recent lessons into context; lead, builder, and reviewer read them every run. |
| Agent SDK and other agents | `sdk/dts2-run.py`: auth from env key, a key command you choose (for example an Anthropic CLI), or the existing Claude login. Optional Codex or Gemini second opinion. |
| Scale teams | `scout` sizes the job, `run` picks tier S/M/L/XL: up to 6 parallel builders on disjoint lanes, up to 4 reviewers by axis, git worktrees for large jobs. |

## Components
- Agents: lead, builder, reviewer, verifier, scout, auditor
- Skills: onboard, machine-prep, setup, run, learn, sdk
- Hooks: SessionStart (lessons), Stop (typecheck and lint)
- Settings: `.claude/dts2-harness.local.md` (template in `templates/`)

## Settings
Copy `templates/dts2-harness.local.md` to `<repo>/.claude/dts2-harness.local.md`. Keys: `enabled`, `stop_checks`, `lessons_inject`, `lessons_max`, `auto_scale`, `max_builders`, `max_reviewers`, `use_worktrees`, `second_opinion`, `profile`. Restart Claude Code after editing.

## Requirements
- Claude Code with plugin support
- Python 3.10+ for the scripts (`python3`, `python`, or `py -3`)
- bash for hooks (Git Bash on Windows, which Claude Code already uses)
- Optional: `claude-agent-sdk` for the headless runner; `codex` or `gemini` CLI for second opinions

## Install
Inside Claude Code:
```
/plugin marketplace add Dobeu-tech-eco/dts2-marketplace
/plugin install dts2-harness@dts2
```
On Claude Code 2.1.275 or later this also works in one step:
```
/plugin install dts2-harness --marketplace Dobeu-tech-eco/dts2-marketplace
```
Restart Claude Code, then run `/dts2-harness:onboard`.
