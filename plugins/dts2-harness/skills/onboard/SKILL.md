---
name: onboard
description: Explain the dts2 harness — its six agents, eight skills, agent roster, team tiers, lessons memory, and headless runner — and recommend where to start. Use when the user asks what dts2 does, how to use it, which skill fits a job, or is new to the harness on this machine or repo.
---

# dts2 harness — orientation

Explanation only. Do not invoke agents or change files from this skill.

## Agents (all prefixed `dts2-harness:`)
- `lead` plans a DAG of tasks and groups them into lanes with exclusive file ownership.
- `builder` implements one lane. Several builders can run at once on separate lanes.
- `reviewer` returns severity-rated findings on one axis or all axes. Never edits.
- `verifier` runs configured commands and checks for stubs. Never edits.
- `scout` sizes a repo or workspace and recommends a team tier.
- `auditor` inventories this machine's agent tooling against a blueprint profile.

## Skills
| Skill | Use it to |
|---|---|
| `machine-prep` | Scan the computer, prune plugins to the blueprint keep-set, set up the slim startup. Once per machine. |
| `setup` | Scaffold `.harness/` in one repo, many repos at once, or a multi-repo workspace. |
| `run` | Do a task: scout sizes it, lead plans, N builders build, reviewers and verifier check. Two checkpoints: Plan checkpoint and Ship checkpoint. Open secrets and decisions go to `.harness/action-items.md`; close a secret with `run add secret NAME`. |
| `learn` | Turn reviewer findings into lessons that every future run reads. |
| `sdk` | Run the same pipeline headless with the Agent SDK, with API key, key command, or your existing Claude login. |
| `evolve` | Change the harness itself in its source repo: edit, validate, test, bump both manifests, commit; push only on an explicit yes. |
| `gtm` | Go-to-market in one pass through the `marketing-skills` plugin, ending in a `readiness.md` scorecard. |

Every run checks which agents are usable and what budget is left (the budget check), then assigns work by cost tier, cheapest capable agent first.

## Agent roster (`profiles/agents/`)
| Agent | Invocation | Typical role |
|---|---|---|
| claude | live | lead, verifier, builder, reviewer |
| codex | live | builder, second-opinion reviewer |
| gemini | live | second-opinion reviewer |
| opencode | live | builder |
| copilot | live or handoff | builder, security reviewer |
| cursor | handoff | builder |
| antigravity | handoff | builder |

Only agents detected on this machine join the roster; handoff agents get a lane file and the run pauses until you report it done.

## Where to start
1. New machine or cluttered tooling → `machine-prep`.
2. New repo or repos → `setup`.
3. Any multi-file task → `run`.
4. After a few runs → `learn`.
5. CI, cron, or a second machine without the desktop app → `sdk`.
6. Changing the harness itself → `evolve`. Launching a product → `gtm`.

## Tiers the run skill picks automatically
| Tier | Typical size | Builders | Reviewers |
|---|---|---|---|
| S | under 20k LOC, single package | 1 | 1 (all axes) |
| M | under 150k LOC or a small monorepo | up to 2 | correctness, security |
| L | under 600k LOC | up to 4 | + performance |
| XL | larger | up to 6 | + style |

Worktrees are used only in workspace mode or when `use_worktrees: always` is set; single mode shares the tree on separate file sets.

Builders never exceed the number of lanes the lead found, and never exceed `max_builders` in `.claude/dts2-harness.local.md`.

Keep the reply under 200 words unless the user asks for detail. Single-file fixes do not need the harness.
