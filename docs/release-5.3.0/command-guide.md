# dt 5.3.0: the commands in plain words

## For people

Run `/dt:onboard` once, then use `/dt:go` for everything after that. You only need the `dt` plugin. Fleet-ledger is optional.

## For agents

- Do not run user-only commands (`composio`, `dpp-full`, `fullauto`, `knowledge`, `machine-prep`, `model`, `onboard`, `sdk`) unless the person typed them.
- The runtime must not depend on fleet-ledger or Supabase. `tests/test_fleet_ledger_optional.py` enforces this.
- `plugins/dts2-runtime/docs/COMMANDS.md` is the source for exact flags.

## All 29 commands

The dt plugin has 29 slash commands. Most people only need three of them:

1. `/dt:onboard` the first time.
2. `/dt:go` every time after that. It looks at the repo, picks the next command and runs it.
3. `/dt:check-in` when you want to know where things stand.

This guide covers all 29. Each row says what the command does and why it stays. Exact flags are in `plugins/dts2-runtime/docs/COMMANDS.md`. The longer table, with examples, is in `plugins/dts2-runtime/COMMAND-GUIDE.md`.

**User-only commands** never start on their own. A person has to type them: `composio`, `dpp-full`, `fullauto`, `knowledge`, `machine-prep`, `model`, `onboard`, `sdk`.

**Fleet-ledger is optional.** Every command here works with only `dt` installed. None of them needs the fleet-ledger plugin or Supabase. A test (`tests/test_fleet_ledger_optional.py`) fails the build if any part of the runtime starts to depend on it.

## Getting started

| Command | What it does | Why keep it |
|---|---|---|
| `/dt:onboard` | Explains the plugin and where to start. It offers optional Composio and hooks steps. | It is the only guided first-day path. Without it, new users guess which command to use. |
| `/dt:machine-prep` | Turns off extra plugins, subagents and skills on this computer. It backs up settings first and never deletes anything. | Too many installed tools slow every session down. You run it once per computer. |
| `/dt:composio` | Optional. Connects a Composio account and turns off local tools that Composio already covers. | Duplicate tools slow startup. `/dt:go` asks for this decision once, as rung 1. |
| `/dt:setup` | Interviews you until the goal is written down and approved, then creates the `.harness` files. | Every later step needs an approved target. `/dt:go` sends you here when there is none. |
| `/dt:model` | Picks which AI provider fills the lead, advisory and sign-off seats, and sets limits on pay-as-you-go providers. | It controls who plans and who pays. A provider that has no rules is read-only. |

## Everyday work

| Command | What it does | Why keep it |
|---|---|---|
| `/dt:run` | Does one task: plan, build, review, verify, receipt and PR. You approve the plan and the ship. | It is the core command and has two human checkpoints. `/dt:go` uses it for single sections, deploys and acceptance. |
| `/dt:steer` | Redirects a run in progress without losing work. It checkpoints, re-plans and resumes. | Without it, changing direction mid-run meant a manual stop and lost work. |
| `/dt:feature` | Plans a new feature and opens a plan PR. It builds nothing. | It keeps the roadmap docs in one place before anyone builds. |
| `/dt:ship` | Turns a hand-built branch into a checked PR with checks, a secret scan, review and a receipt. It never merges. | Hand-made branches skipped checks. It now runs the same release gate as CI. |
| `/dt:gtm` | Runs one go-to-market pass and ends with a launch-readiness scorecard. | Launch checks were scattered across tools. |

## Unattended and parallel runs

| Command | What it does | Why keep it |
|---|---|---|
| `/dt:autopilot` | Runs chosen steps with no human checkpoints. A three-provider gate replaces the checkpoints. It keeps at most 5 PRs open. | It handles well-defined work you trust to run on its own. |
| `/dt:dpp` | Runs several autopilot lanes in parallel and merges them in order. | It is faster for independent items. `/dt:go` picks it when 2 or more sections are still to do. |
| `/dt:dpp-full` | Like dpp, but it keeps filling lanes from a delegation scan. User-only. | It works through a big backlog with less supervision. |
| `/dt:fullauto` | dpp-full with autopilot on, looping until nothing is left. A stop file, a stall or a spent budget stops it. User-only. | It finishes a whole end state overnight within budget caps. A redesign is deferred until the Fleet Ledger pilot. |
| `/dt:sdk` | Runs the pipeline headless with the Claude Agent SDK, for CI or cron. User-only. | Servers have no chat window. It never pushes. |
| `/dt:cooldown` | Pauses a provider that hit its usage limit until the limit resets. | It stops sessions from calling a provider that has run out of usage. |

## Status and memory

| Command | What it does | Why keep it |
|---|---|---|
| `/dt:go` | Reads the repo and runs the next command it needs, from setup through to complete. It stops at approvals, at a stop file, and whenever a person is needed. | It is the one command that guides a user through the rest. Fleet-ledger is not needed. |
| `/dt:check-in` | A read-only progress checklist against the goal. With `all`, it reports every session on this computer. | It answers "where are we?" in one step. |
| `/dt:action-items` | Lists what needs a person, such as secrets, decisions and deploys. | Runs stalled silently on human-only tasks. `/dt:go` sends you here at rung 7. |
| `/dt:fleet` | Lists the dt sessions on this computer and broadcasts a note to them. | It is the only way to reach many terminal sessions at once. It uses local files, not Supabase. |
| `/dt:incidents` | Shows role incidents that hooks record automatically, and reviews them for root causes. | Without it, mistakes repeated and nothing recorded them. |
| `/dt:learn` | Turns reviewer findings into lessons that later runs read. | It stops the same mistake from coming back. `/dt:go` ends here at rung 10. |
| `/dt:loop` | Tests one change to a role's instructions against past receipts, within fixed caps. | It tunes role instructions with evidence, not guesses. |
| `/dt:knowledge` | Your personal store of preferences and terms, shared across your devices. User-only. It never stores secrets. | Your defaults follow you between repos and machines. |

## Maintenance

| Command | What it does | Why keep it |
|---|---|---|
| `/dt:find-skills` | Rescans the repo and ranks up to 12 improvements, such as skills, hooks, MCP servers and CI. It wires in only the ones you pick. | It covers the "tooling round" on demand, so `/dt:setup` stays short. |
| `/dt:ask-expert` | Reviews one repo and votes keep, fold, template, archive or delete. It changes nothing. | It helps you decide whether a repo is worth keeping. |
| `/dt:repo-sweep` | Runs a quick ask-expert pass on every repo an owner has, then shows one cleanup screen. It never bulk deletes. | Cleaning up repos one at a time was too slow. |
| `/dt:pr-sweep` | Clears open and stale PRs. It merges green ones, rebases the rest, and closes dead ones with a comment. | Autopilot leaves PRs behind. `/dt:go` runs it at rung 6. |
| `/dt:evolve` | Changes the plugin at its source repo. It pushes only after your yes. | It is the maintainers' safe route into the plugin. |

## Why nothing was cut

The council looked for commands to retire and kept all 29:

- **They are layered.** `/dt:go` calls the others, so a user only needs to learn `/dt:go`. Removing a command would remove a rung from the ladder or a tool from maintainers.
- **Removals cost a major version.** Dropping a command is a breaking change, and the 6.0.0 line is already taken by the directory edition. See `council-plan.md`, rule 2.
- **The overlaps are deliberate.** `dpp`, `dpp-full` and `fullauto` are three levels of how much you supervise. `ask-expert` and `repo-sweep` are the same review for one repo or many.
