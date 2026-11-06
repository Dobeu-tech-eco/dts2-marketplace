---
name: onboard
description: Explain the dts2 harness (seven agents, eighteen skills, roster, team tiers, lessons, headless runner) and recommend where to start. Use when the user asks what dts2 does, how to use it, which skill fits a job, or is new to the harness.
disable-model-invocation: true
---

# dts2 harness — orientation

This skill explains only, except the optional hooks step at the end, which changes files only after the user picks hooks. Do not invoke agents.

## Agents (all prefixed `dts2:`)
- `lead` plans a DAG of tasks and gives each builder a separate file set.
- `builder` implements one builder section; several builders can run at once on separate file sets.
- `reviewer` returns severity-rated findings on one axis or all axes. Never edits.
- `verifier` runs configured commands and checks for stubs. Never edits.
- `scout` sizes a repo or workspace and recommends a team tier.
- `auditor` inventories this machine's agent tooling against a blueprint profile.

## Skills
| Skill | Use it to |
|---|---|
| `machine-prep` | Scan the computer, prune plugins to the blueprint keep-set, set up the slim startup. Once per machine. |
| `setup` | Interview to an approved end state, then scaffold `.harness/` in one repo, many repos, or a multi-repo workspace. |
| `run` | Do a task: scout sizes it, lead plans, N builders build, reviewers and verifier check. Two checkpoints: Plan checkpoint and Ship checkpoint. Open secrets and decisions go to `.harness/action-items.md`; close a secret with `run add secret NAME`. |
| `learn` | Turn reviewer findings into lessons that every future run reads. |
| `sdk` | Run the same pipeline headless with the Agent SDK, using your existing Claude login, or an API key or key command for CI. |
| `evolve` | Change the harness itself in its source repo: edit, validate, test, bump both manifests, commit; push only on an explicit yes. |
| `action-items` | List open secrets, decisions, handoffs, deploy steps and promotions with the command that resolves each; `done`, `add`, `assign`. Pass-off for any agent: `.harness/handoff/latest.md`, resumed with `run resume`. |
| `gtm` | Go-to-market in one seamless pass: auto-installs `marketing-skills` if missing, runs a deep-dive, picks the applicable skills, and ends in a `readiness.md` scorecard. |
| `ship` | `/dts2:ship` opens a PR on your own initiative: pre-check, type/lint/test/build, secret and do-not-touch scan, verifier and reviewer, receipt, PR template, push and open; then sweeps PRs and branches so only main and dev remain. Never merges. |
| `feature` | `/dts2:feature <idea>` adds a feature to the roadmap: clarity score, a scoped deep interview when it is unclear, the lead writes it into the end state and every plan doc, then a PR. |
| `autopilot` | `/dts2:autopilot <steps>` runs steps unattended: three frontier providers must agree on the plan and the build (Claude Fable 5.1 breaks a split), one PR per step merged on green CI before the next. Progress shows in check-in. |
| `dpp` | `/dts2:dpp [dry-run]` runs up to five autopilot lanes in parallel as headless sons under one head: lane plan and feasibility from the check-in list, approval, supervision, serialised merges, one report and the task ledger. |
| `dpp-full` | `/dts2:dpp-full` is dpp with `--full`: delegation scan for extra lanes and continuous dispatch without a new approval. |
| `fullauto` | `/dts2:fullauto` is dpp-full with autopilot on, looping check-in between rounds until nothing is outstanding and every lane is done or blocked in the ledger. |
| `model` | `/dts2:model` picks which agent provider leads (the lead, advisory and sign-off seats); default Claude. Builders are unaffected. |
| `find-skills` | `/dts2:find-skills` is available any time: rescan the repo, answer one to three questions, get suggested skills, and wire the ones you pick into the project. |
| `ask-expert` | `/dts2:ask-expert [repo]` is available any time, before setup: tell it your goal, and an expert panel reads the code and writes a one-page memo: keep, fold into another repo, sell as a template, archive or delete. |
| `repo-sweep` | `/dts2:repo-sweep [owner]` does the same quick pass over all your repos, oldest first, then one cleanup screen. Archive is reversible; delete is one repo at a time with a backup and a typed name. |
| `check-in` | `/dts2:check-in` is available any time: a read-only checklist from where the project started through the approved end state, each item marked complete or outstanding, with an `N of M complete` percent. |

Setup and run pull in companion skills from mattpocock/skills at the moment they are needed (grill-me, improve-codebase-architecture, writing-for-agents, pr, resolve-merge-conflicts (from warpdotdev/common-skills, since mattpocock retired its version), plus ask-matt and research for your questions, improve-codebase-architecture again before tests, diagnosing-bugs again at the hard 5-round fix cap, loop-me when a run starts, setup-pre-commit once per repo at the commit gate, and code-review on first contact with a new repo), recorded in keep.yaml. A pre-check before every run command installs any that are missing, proposes updates for you to approve (it never updates them in bulk), swaps one that is gone upstream, refreshes plugin marketplaces, and when a newer harness is published saves your spot and upgrades; the next run finishes the upgrade itself (there is no separate upgrade command). After every ship, open harness lessons are offered through evolve automatically.

Setup maps the whole project into sections; `run` keeps builders busy on ready sections and parks stuck ones instead of stopping. The `run` skill pivots to the workspace root when started inside a member repo, and a context guard stops it and re-runs setup on a context spike.

## How work is organized
The frontier tier is for advice and sign-off only (the lead, the reviewers' final review, the verifier). Builders never run a frontier model: they run the cheapest capable model at a complexity-scaled effort (`scripts/delegate.py`), each in its own worktree. A stalled lead hands off and fails over to the next eligible provider, and every detected agent gets a seeded project memory file at scaffold. One run branch per task; you push and open the PR with the receipt. `run review-pr <n>` reviews an existing PR.

Every run checks which agents are usable and what budget is left (the budget check), then assigns work by cost tier, cheapest capable agent first.

## Agent roster (`profiles/agents/`)
| Agent | Invocation | Typical role |
|---|---|---|
| claude | live | lead, verifier, builder, reviewer |
| codex | live | builder, second-opinion reviewer |
| gemini | live | builder, reviewer, second-opinion reviewer |
| grok | live | builder, reviewer, second-opinion reviewer |
| opencode | live | builder |
| muse | live | builder, second-opinion reviewer |
| copilot | live | builder, security reviewer |
| cursor | handoff | builder |
| antigravity | handoff | builder |

Only agents detected on this machine join the roster; handoff agents get a written brief, and the run pauses until you report it done.

## Where to start
1. New machine or cluttered tooling → `machine-prep`.
2. New repo or repos → `setup`.
3. Any multi-file task → `run`.
4. After a few runs → `learn`.
5. CI, cron, or a second machine without the desktop app → `sdk`.
6. Changing the harness itself → `evolve`. Launching a product → `gtm`.
7. Optional Claude Code hooks (command guard, auto-format, tests on stop, notifications) → the Hooks step below.
8. Many app plugins or MCP servers → `composio` (one connection, then trim overlap).
9. Database tooling: `/dts2:find-skills` suggests database MCP servers and skills for your stack.
10. Not sure a repo is worth keeping → `/dts2:ask-expert` for one repo, `/dts2:repo-sweep` for many.

## Offer ask-expert when the user doubts a repo
When the user's answers show doubt about keeping a repo (it is old, unused, abandoned, or they are thinking of deleting or archiving it), suggest `/dts2:ask-expert` before setup, in one sentence. For many such repos, suggest `/dts2:repo-sweep`. Only suggest; do not start either.

## Tiers the run skill picks automatically
| Tier | Typical size | Builders | Reviewers |
|---|---|---|---|
| S | under 20k LOC, single package | 1 | 1 (all axes) |
| M | under 150k LOC or a small monorepo | up to 2 | correctness, security |
| L | under 600k LOC | up to 4 | + performance |
| XL | larger | up to 4 | + style |

Worktrees are used only in workspace mode or when `use_worktrees: always` is set; single mode shares the tree on separate file sets.

Builders never exceed the number of builder sections the lead planned, and never exceed `max_builders` in `.claude/dts2-harness.local.md`.

## Composio (optional)
Ask once with AskUserQuestion: "Do you have a Composio account?" (yes or no). Composio is one connection to 1000+ apps, so agents need fewer separate plugins and MCP servers. On either answer, hand off to `/dts2:composio`, which records the answer, installs and maps on yes, and offers a signup link on no. Skip the question if `~/.dts2/composio.json` already holds a decision. Nothing is changed here; `/dts2:composio` asks before it disables anything.

## Hooks (optional last step)
The plugin's own hooks are already active: the policy gate, the merge guard, the stop checks and the context guard. Toggles are in `.claude/dts2-harness.local.md`. This step offers extra hooks for the user's project.

1. Run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/hooks-setup.py" recommend`.
2. Show the recommended hooks as a short table: hook, when it runs, why, already present.
3. Ask once with AskUserQuestion (multi-select) which to add, and the scope: project (shared, the default), local, or user.
4. On picks, run `hooks-setup.py apply --ids ... --scope ... --dry-run`, show the result, then run `apply` for real.
5. Report what was added, what was skipped and the backup path.

When a database is detected, `db-guard` (blocks destructive database commands) and `migration-check` (reminds you to review migrations) are recommended too. The harness never runs destructive database actions; it always asks.

Existing hooks are never overwritten or removed. Nothing is written without a pick. `/hooks` in Claude Code shows the result.

Keep the reply under 200 words unless the user asks for detail. Single-file fixes do not need the harness.
