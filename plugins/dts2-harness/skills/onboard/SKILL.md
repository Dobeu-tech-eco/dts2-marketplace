---
name: onboard
description: Explain the dts2 harness — its six agents, six skills, team tiers, lessons memory, and headless runner — and recommend where to start. Use when the user asks what dts2 does, how to use it, which skill fits a job, or is new to the harness on this machine or repo.
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
| `run` | Do a task: scout sizes it, lead plans, N builders build, reviewers and verifier check. Two approval gates. |
| `learn` | Turn reviewer findings into lessons that every future run reads. |
| `sdk` | Run the same pipeline headless with the Agent SDK, with API key, key command, or your existing Claude login. |

## Where to start
1. New machine or cluttered tooling → `machine-prep`.
2. New repo or repos → `setup`.
3. Any multi-file task → `run`.
4. After a few runs → `learn`.
5. CI, cron, or a second machine without the desktop app → `sdk`.

## Tiers the run skill picks automatically
| Tier | Typical size | Builders | Reviewers | Worktrees |
|---|---|---|---|---|
| S | under 20k LOC, single package | 1 | 1 (all axes) | no |
| M | under 150k LOC or a small monorepo | up to 2 | correctness, security | no |
| L | under 600k LOC | up to 4 | + performance | yes |
| XL | larger | up to 6 | + style | yes |

Builders never exceed the number of lanes the lead found, and never exceed `max_builders` in `.claude/dts2-harness.local.md`.

Keep the reply under 200 words unless the user asks for detail. Single-file fixes do not need the harness.
