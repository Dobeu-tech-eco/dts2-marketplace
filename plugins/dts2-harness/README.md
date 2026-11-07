# dt: the Dobeu Harness for Claude Code

`dt` is a Claude Code plugin that turns "do this task" into a planned, built, reviewed and verified pull request, with a person approving at the points that matter and a written record of everything that happened. It is made and maintained by [Dobeu Tech Solutions LLC](https://dobeu.net) and released under the Dobeu Source-Available License (see [License](#license)).

## What it is

A set of slash commands (`/dt:run`, `/dt:ship`, `/dt:dpp` and more), eight specialist agents and a few safety hooks that sit on top of Claude Code. You describe the end state you want once. After that, a scout sizes the job, a lead plans it, builders work in parallel on separate files, reviewers and a verifier check the result, and you get a receipt and a PR. Nothing merges or deploys without the approvals you set.

## The problem it solves

Plain agent sessions are great for small edits and shaky for big ones. The usual failure modes are the ones this plugin is built around:

- **Drift.** Long tasks lose the plot. `dt` keeps an approved end state (`.harness/end-state.md`) and measures progress against it with `/dt:check-in`.
- **Self-review.** An agent that grades its own work finds little wrong. Here the builder never reviews itself; separate reviewer and verifier agents do, and findings become lessons that later runs read.
- **Collisions.** Parallel agents overwrite each other. Each builder owns a disjoint set of files, and parallel runs use one git worktree per lane with merges serialised by a head session.
- **Runaway spend and risky actions.** Frontier models are reserved for planning and sign-off, builders use the cheapest capable model, spend caps apply, and a policy gate blocks force-push, `--admin`, deploy CLIs and secret changes unless you approved them.
- **Lost context.** Sessions end. A handoff file (`.harness/handoff/latest.md`) lets any agent resume with `/dt:run resume`.

## Who it is for

Developers and small teams who already use Claude Code and want a repeatable way to run larger changes: multi-file features, cross-repo work, backlogs of roadmap items, cleanup passes. If your tasks fit in a single prompt, you do not need it.

## Requirements

- Claude Code with plugin support.
- Python 3.10 or newer (`python3`, `python`, or `py -3`). The scripts use only the standard library.
- bash for the hooks (Git Bash on Windows, which Claude Code already uses), and `git`.
- The `gh` CLI, signed in, for anything that opens or sweeps pull requests (`ship`, `pr-sweep`, `dpp`, `autopilot`).
- Linux, macOS, WSL or Docker for parallel runs. On native Windows `dpp` parks with the reason `windows-native` (see [docs/RUNTIMES.md](docs/RUNTIMES.md)).
- Optional: `claude-agent-sdk` for the headless runner; the CLIs of other agents (`codex`, `gemini`, `grok`, `opencode`, `copilot`, `muse`) if you want them on the roster. `autopilot` votes across three providers, so it needs three of them installed and signed in.

`python3 scripts/doctor.py` from the plugin folder (or `make doctor` in a clone of the marketplace repo) checks all of this on your machine.

## Install

Inside Claude Code:

```
/plugin marketplace add Dobeu-tech-eco/dts2-marketplace
/plugin install dt@dts2
```

On Claude Code 2.1.275 or later this also works in one step:

```
/plugin install dts2 --marketplace Dobeu-tech-eco/dts2-marketplace
```

Restart Claude Code (or run `/reload-plugins`), then run `/dt:onboard`. The plugin is named `dt`, so commands are `/dt:<command>` and agents are `dt:<agent>`; the marketplace is named `dts2`.

If your `claude` command in WSL wraps the Windows `claude.exe`, both shells share the Windows Claude home: install once from Windows. Install inside WSL only when you run the native Linux CLI there.

## Wire it up

1. **Orient.** `/dt:onboard` explains the agents and skills, recommends where to start, and offers optional extra hooks as its last step. It changes nothing until you pick.
2. **Tidy the machine (once).** `/dt:machine-prep` audits your installed plugins, agents and MCP servers against a blueprint, then disables the overlap (with a settings backup first). It also disables older `harness` and `harness-ops` copies so agents are not duplicated.
3. **Set up a repo.** In the repo, run `/dt:setup`. It interviews you until you approve an end state, then scaffolds `.harness/` (end state, config, CI workflow, `.gitignore` entries, agent memory files). Use `/dt:setup path1 path2` for several repos, or a workspace file for a multi-repo project. `/dt:ask-expert` can first help you decide whether a repo is worth keeping.
4. **Review the settings.** Copy `templates/dts2-harness.local.md` to `<repo>/.claude/dts2-harness.local.md` and edit the keys you care about (full list under [Settings](#settings)). Restart Claude Code after editing.
5. **Choose hooks.** The plugin's own hooks (policy gate, merge guard, stop checks, context guard, lessons, handoff) are active as soon as it is installed; each honours `enabled` in the settings file. For extras (command guard, auto-format, tests on stop, notifications, merge on green, database guards), the last step of `/dt:onboard` runs `scripts/hooks-setup.py recommend`, shows a table, and adds only the ones you pick, with a backup and a dry run first.
6. **Choose who leads.** Claude leads by default. `/dt:model` switches the lead, advisory and sign-off seats to another installed provider. Other agents join the roster automatically when their CLI is detected.
7. **Optional integrations.**
   - Composio, one connection to many apps: `/dt:composio`.
   - Headless runs for CI, cron or servers with the Agent SDK: `/dt:sdk`.
   - A private, synced store for your standing preferences and glossary: `/dt:knowledge`.
   - Go-to-market pass through the external `marketing-skills` plugin: `/dt:gtm`.
   - Impeccable and marketing-skills are separate plugins; the harness uses them when installed and does not bundle them.
   - API-key agents (`claude-api`, `codex-api`, `grok-api`): [docs/API-AGENTS.md](docs/API-AGENTS.md).

### Where things live

| Location | What it holds |
|---|---|
| `<repo>/.claude/dts2-harness.local.md` | Per-repo settings (template in `templates/`). |
| `<repo>/.harness/end-state.md` | The approved end state every run is measured against. |
| `<repo>/.harness/config.yaml` | Budgets, council, merge target, shared files, timeouts. |
| `<repo>/.harness/` (the rest) | Lessons, state, handoff, action items, receipts, run records. Run records and receipts are kept out of git. |
| `<repo>/.claude/settings.local.json` | Your approvals under `dts2_approvals`. Only a person edits this file; agents cannot. |
| `~/.dts2/` | Machine-wide state: fleet registry, agent cooldowns, Composio map, repo backups, knowledge store. |

## Day to day

The commands most people start with:

| Group | Commands | What they do |
|---|---|---|
| Get going | `/dt:onboard`, `/dt:setup` | Learn the harness; set a repo up against an approved end state. |
| Do the work | `/dt:run <task>` | One task, with a Plan checkpoint and a Ship checkpoint where you answer `approve`, `edit` or `stop`. Ends with a receipt and a PR. |
| | `/dt:run resume` | Pick up a parked or interrupted run. |
| | `/dt:feature <idea>` | Put a feature on the roadmap and open a plan PR, without building it. |
| | `/dt:steer <new direction>` | Stop running work and redirect it. Typing while a run is going is also safe; prompts are queued, not lost. |
| Ship | `/dt:ship` | Open a PR for the branch you are on, after checks, a secret scan and review. Never merges. |
| | `/dt:pr-sweep` | Clear open and stale PRs: merge green ones, triage red CI, close dead ones. |
| See where you are | `/dt:check-in` | Read-only progress against the end state, `N of M complete`. |
| | `/dt:action-items` | Secrets, decisions and handoffs waiting on a person, with the command that resolves each. |
| Run more, hands off | `/dt:autopilot <steps>` | Steps without human checkpoints, behind a three-provider vote. One PR per step. |
| | `/dt:dpp`, `/dt:dpp-full`, `/dt:fullauto` | Several lanes in parallel under one head session. `dpp dry-run` shows the plan first. |
| Look after the harness | `/dt:learn`, `/dt:incidents`, `/dt:fleet`, `/dt:cooldown` | Turn findings into lessons; review agent incidents; see every harness session on this computer; pause an agent that hit a usage limit. |
| | `/dt:find-skills`, `/dt:repo-sweep`, `/dt:ask-expert` | Suggest skills and tooling for a repo; sweep your repos; get a keep, fold, archive or delete memo. |

A typical first session: `/dt:onboard`, then `/dt:setup` in a repo, then `/dt:run add rate limiting to the public API`. Approve the plan, let it build, approve the ship summary, and review the PR.

Which command when, and why: [docs/GUIDE.md](docs/GUIDE.md). Exact invocation of every command: [docs/COMMANDS.md](docs/COMMANDS.md).

## All commands

Every slash command in the plugin (27). Commands marked "never starts on its own" run only when you type them. Exact flags are in [docs/COMMANDS.md](docs/COMMANDS.md).

| Command | What it does | Example |
|---|---|---|
| **Getting started** | | |
| `/dt:onboard` | Tour of the plugin, its agents and commands; optional Composio and extra-hooks steps at the end. Never starts on its own. | `/dt:onboard` |
| `/dt:machine-prep` | Audits installed plugins, agents and skills, then disables overlap (never deletes; settings backed up first). Never starts on its own. | `/dt:machine-prep` |
| `/dt:composio` | Optional Composio setup: connects your account, maps toolkits, offers to disable tools Composio already covers. Never starts on its own. | `/dt:composio` |
| `/dt:setup` | Interviews you until the end state is approved, then scaffolds `.harness/` for one repo, several repos or a workspace. | `/dt:setup` or `/dt:setup --scaffold-only` |
| `/dt:model` | Chooses which provider (Claude, Codex, Gemini) leads, advises and signs off; adds, renames and limits named agents. Never starts on its own. | `/dt:model` |
| **Everyday work** | | |
| `/dt:run` | One task end to end: plan, parallel build, review, verify, receipt and PR. You approve the plan and the ship. | `/dt:run add rate limiting to the API`, `/dt:run resume` |
| `/dt:steer` | Redirects a running task without losing work: checkpoint, re-plan, resume. | `/dt:steer use the Postgres schema instead` |
| `/dt:feature` | Puts a feature on the roadmap and opens a plan PR. Builds nothing. | `/dt:feature "nightly report email"` |
| `/dt:ship` | Turns your branch into a checked PR (checks, secret scan, review, receipt). Never merges. | `/dt:ship` |
| `/dt:pr-sweep` | Clears open and stale PRs: merges green ones, triages red CI, closes dead ones, lists what waits on you. | `/dt:pr-sweep` |
| `/dt:gtm` | One go-to-market pass ending in a launch-readiness scorecard. | `/dt:gtm` |
| **Unattended and parallel** | | |
| `/dt:autopilot` | Runs chosen steps with no human checkpoints, behind a three-provider vote. One PR per step. | `/dt:autopilot 3-5` |
| `/dt:dpp` | Runs several autopilot lanes in parallel under one head session and merges them in order. | `/dt:dpp dry-run` |
| `/dt:dpp-full` | dpp that also fills lanes from a backlog scan and keeps dispatching. Never starts on its own. | `/dt:dpp-full` |
| `/dt:fullauto` | dpp-full looping until nothing is outstanding, within budget and stall guards. Never starts on its own. | `/dt:fullauto` |
| `/dt:sdk` | Sets up headless runs with the Claude Agent SDK for CI, cron or servers. Never starts on its own. | `/dt:sdk` |
| `/dt:cooldown` | Pauses an agent that hit a usage limit until it resets; shared by every session on the machine. | `/dt:cooldown set codex 2d` |
| **Status and memory** | | |
| `/dt:check-in` | Read-only progress against the end state, `N of M complete`; `all` covers every session on this computer. | `/dt:check-in`, `/dt:check-in all` |
| `/dt:action-items` | What is waiting on a person (secrets, decisions, handoffs, deploys), with the command that resolves each. | `/dt:action-items` |
| `/dt:fleet` | Lists every dt session on this computer and broadcasts a note, handoff or pause to them. | `/dt:fleet` |
| `/dt:incidents` | Agent misfires recorded by hooks, what is running now, and a root-cause review of open incidents. | `/dt:incidents review` |
| `/dt:learn` | Turns reviewer findings into per-repo lessons later runs read. | `/dt:learn promote L-012` |
| `/dt:knowledge` | Your private, synced store of preferences and terms across devices. Never stores secrets. Never starts on its own. | `/dt:knowledge setup` |
| **Maintenance** | | |
| `/dt:find-skills` | Rescans the repo and suggests up to 12 skills, hooks, MCP servers and other tooling; adds only your picks. | `/dt:find-skills` |
| `/dt:ask-expert` | Reviews one repo and returns a keep, fold, template, archive or delete memo with a scorecard. Changes nothing. | `/dt:ask-expert my-old-repo` |
| `/dt:repo-sweep` | A quick ask-expert pass on every repo of an owner, then one cleanup screen. Delete is never bulk. | `/dt:repo-sweep Dobeu-tech-eco` |
| `/dt:evolve` | Changes the plugin at its source repo: edit, test, bump the version, commit. Pushes only on your yes. For maintainers. | `/dt:evolve` |

## Parallel autopilot
| Skill | What it does |
| --- | --- |
| `dpp` | `/dt:dpp [dry-run]` plans lanes from the check-in list (`lanes.py plan` + feasibility `check`, `estimated_spend` per lane), gets approval, starts one headless autopilot son per lane in its own worktree, supervises (status, head-answered questions, two send-backs, second opinion), serialises merges with `merge-go.md`, rolls lessons up, and ends with `dpp-report.md` plus the task ledger. |
| `dpp-full` | `dpp --full`: a delegation scan adds sons' questions, parked items and new action items as lane candidates; continuous dispatch starts the next lane without asking. |
| `fullauto` | `dpp-full` with autopilot forced on, re-running check-in between rounds until nothing is outstanding and every lane is done or blocked with its items in the ledger. |

Model calls that the harness scripts start go through `scripts/model_call.py` (one machine-wide limit, `supervisor.max_model_calls`); Agent-tool seats (`dt:reviewer`) run inside the host session and cannot be gated by that limit. The `max_usd` cap covers Claude spend only: a call from a non-Claude CLI prints no cost, is counted as `unreported_calls` in `budget.json` and shown by `lanes.py budget`, and never stops a run. Full notes are in CHANGELOG.md under 3.10.0.

## Agent roster
One profile per agent in `profiles/agents/`. `tokenBurn` is a relative, user-editable weight, not a price or a quota; it only ranks agents for a seat (lower is cheaper to run). Effort support beyond `medium` is verified only for claude and codex; every other row is a user-editable default.

| Agent | Models (frontier / standard / economy) | Roles and specialization | tokenBurn (standard) | Effort support |
|---|---|---|---|---|
| claude | opus / sonnet / haiku | lead, verifier, builder, reviewer; plans, signs off and reviews | 3 | low, medium, high, max |
| codex | gpt-6-astra / gpt-6.1-sol / gpt-6-luna | builder, second-opinion; self-contained implementation and independent review | 3 | low, medium, high, xhigh (max and ultra only when requested; luna has no ultra) |
| gemini | gemini-2.5-pro / gemini-2.5-flash / gemini-2.5-flash-lite | builder, reviewer, second-opinion (via the Antigravity `agy` CLI) | 2 | medium |
| grok | grok-4.7 / grok-4.7 / grok-4-fast | builder, reviewer, second-opinion | 3 | medium |
| opencode | CLI default | builder | 2 | medium |
| copilot | CLI default | builder, security reviewer | 2 | medium |
| muse | muse-spark-1.2 on every tier | builder, second-opinion; Meta's Muse Code terminal agent | 2 | medium |
| cursor | IDE default | builder (handoff, no dispatch) | 0 | medium |
| antigravity | IDE default | builder (handoff, no dispatch) | 0 | medium |

## Delegation
Frontier-tier models are reserved for advice and sign-off: the lead (planning), the reviewers' final whole-diff review, and the verifier. Execution never uses a frontier model. Every builder takes the cheapest capable model and raises effort (low, medium, high, max) for harder work instead of escalating to a pricier model: mechanical is economy at low effort, normal is standard at medium, design is standard at high. Effort before escalation keeps token burn down without cutting the work. `scripts/delegate.py` resolves model and effort for a seat, `violates_execution_policy` flags a builder that ran frontier, and the receipt records a `Delegation policy` line that the final review blocks on.

The provider that fills the lead, advisory and sign-off seats is selectable with `/dt:model` (default Claude); the rule holds whichever provider leads. If the lead hits a usage or token limit or stalls, the harness writes the handoff and fails over to the next eligible provider (`scripts/failover.py`). The pre-check before every run command (`scripts/skills-check.py`) keeps companion and keep-list skills installed and current, refreshes marketplaces, and upgrades the harness in place when a newer version is published (handoff first; the next run finishes the upgrade). `/dt:find-skills` is available any time to rescan the repo and suggest skills. Every detected agent gets a seeded project memory file (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) at scaffold.

## Settings
Copy `templates/dts2-harness.local.md` to `<repo>/.claude/dts2-harness.local.md`. Keys: `enabled`, `stop_checks`, `stop_checks_block`, `lessons_inject`, `lessons_max`, `pr_receipt_template_push`, `auto_scale`, `max_builders`, `max_reviewers`, `continuous_dispatch`, `builder_timeout_min`, `son_permission_mode`, `use_worktrees`, `second_opinion`, `profile`, `end_state_threshold`, `auto_learn`, `context_guard`, `context_guard_tool_calls`, `context_guard_mb`, `context_guard_stop`, `policy_gate` (the declarative policy hook; default `true`), `max_execution_effort`, `delegation_strict`, `lead_provider`, `mailbox_wait_min` (minutes a son waits on the head before it parks), `dpp_full_ask_each_lane` (dpp-full outside autopilot asks before each new lane), `fullauto_freeze_scope` (fullauto freezes the approved item set), `post_merge_fix_attempts` (post-merge fixes per lane before a revert PR opens; default 2), `son_model` (the model every dpp son runs on; default `sonnet`; set `opus` per task for hard lanes). Restart Claude Code after editing.

Approvals are not a harness setting: they are a top-level `dts2_approvals` key in `.claude/settings.local.json` (`{"dts2_approvals": {"merge": ["42"]}}`; kinds `recorded_yes`, `unsafe_no_sandbox`, `blocked_pr_done`, `lane_override`, `merge`), a file only the person edits. Sons are denied writes to it, and `scripts/approvals.py` reads nothing else. A merge that deploys production (`merge: deploys_production: true` in `.harness/config.yaml`) needs its PR number there.

## Update and uninstall

Update:

```
/plugin marketplace update dts2
/reload-plugins
```

The pre-check before every run command also refreshes marketplaces and upgrades the harness in place when a newer version is published (handoff first; the next run finishes the upgrade).

Uninstall:

```
/plugin uninstall dt@dts2
/plugin marketplace remove dts2
```

Uninstalling leaves your repos alone. `.harness/` folders, `.claude/dts2-harness.local.md` and `~/.dts2/` stay until you delete them.

### Migrating from dts2 or dts2-harness

The plugin used to be called `dts2` (before 4.0, `dts2-harness`). Commands are now `/dt:<command>` and agents `dt:<agent>`. The marketplace keeps the name `dts2`.

```
/plugin uninstall dts2@dts2
/plugin marketplace update dts2
/plugin install dt@dts2
/reload-plugins
```

On a version before 4.0 the installed plugin is `dts2-harness`: run `/plugin uninstall dts2-harness@dts2` first. Settings (`.claude/dts2-harness.local.md`) and `.harness/` state are unchanged.

## Troubleshooting

- **Run the doctor first.** `python3 scripts/doctor.py` (plugin folder) reports Python, git, the `claude` CLI, sandbox tools, the auth method (named, never the value) and the platform.
- **`/dt:` commands do not appear.** Restart Claude Code or run `/reload-plugins`, then check `/plugin` shows `dt` as enabled.
- **Every agent shows up twice.** An older `harness`, `harness-ops` or `dts2` copy is still enabled. Disable it under `/plugin`, Installed, or run `/dt:machine-prep`.
- **Settings changes do nothing.** Edits to `.claude/dts2-harness.local.md` need a Claude Code restart.
- **A merge or push was denied.** That is the policy gate or the merge guard working. Merges and default-branch pushes need your approval in `.claude/settings.local.json` under `dts2_approvals`; see [docs/GUIDE.md](docs/GUIDE.md). Refusals are logged in `.harness/merge-guard.log`.
- **`dpp` parks with `windows-native`.** Parallel lanes need POSIX signals. Run under WSL or Docker ([docs/RUNTIMES.md](docs/RUNTIMES.md)).
- **WSL cannot find your Claude settings.** If `claude` in WSL wraps the Windows `claude.exe`, the Windows home is the live one. `python3 scripts/env-detect.py` shows which.
- **A run stopped midway.** `/dt:check-in` shows what is outstanding, `/dt:action-items` shows what is waiting on you, and `/dt:run resume` continues from the handoff file.
- **An agent hit a usage limit.** `/dt:cooldown set <agent> <date or duration>` skips it everywhere until it resets.

## Documentation

- [docs/GUIDE.md](docs/GUIDE.md): how to talk to the harness, which command when, the head, son and council flow. Start here.
- [docs/COMMANDS.md](docs/COMMANDS.md): the command reference, with exact invocation and what each command writes.
- [docs/INVENTORY.md](docs/INVENTORY.md): every skill, agent, hook, script and `lanes.py` subcommand.
- [docs/API-AGENTS.md](docs/API-AGENTS.md) and [docs/RUNTIMES.md](docs/RUNTIMES.md): API-key agents; Windows, WSL and Docker.
- [ARCHITECTURE.md](ARCHITECTURE.md): modules, state port, plan graph, briefs and hook entry points.
- [CHANGELOG.md](CHANGELOG.md): release notes.

## Components

- Agents: lead, builder, fixer, reviewer, verifier, scout, auditor, incident-reviewer
- Skills: onboard, composio, machine-prep, setup, run, learn, evolve, gtm, sdk, action-items, model, find-skills, check-in, ship, feature, autopilot, dpp, dpp-full, fullauto, ask-expert, repo-sweep, pr-sweep, fleet, cooldown, knowledge, incidents, steer
- Hooks: SessionStart (lessons, cooldowns), fleet-session (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd), UserPromptSubmit (prompt intake), PreCompact (handoff), Stop (typecheck and lint), PreToolUse (merge guard, policy gate, spawn dry-run), PostToolUse and PostToolBatch (PR receipt, context guard, subagent report), SubagentStop (report check; verifier check-line gate), StopFailure and PermissionDenied (action-items ledger), SessionEnd (lease release)
- Settings: `.claude/dts2-harness.local.md` (template in `templates/`)

## Known limits

- Login state for gemini, grok, muse, and opencode is self-reported by you; the harness cannot verify it.
- Impeccable and marketing-skills are external plugins. The harness uses them when installed and does not bundle them.
- Grok review and builder commands (`roster.py command`) were exercised on 2026-10-22; model ids stay marked unverified.
- Muse Code CLI flags and the `muse-spark-1.3` model id are unverified and user-editable.
- Effort levels beyond `medium` are verified only for claude and codex.
- The Sol 6.1 roster slot is user-editable; check it matches what you run.

## Acknowledgements

dt builds on patterns from these projects. We learned from them and wrote our own implementation; no code was copied.

- [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (MIT): the deep-interview pattern behind the end-state interview.
- [Impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0): the critique and polish pattern behind the finish pass.
- [marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT): the go-to-market sequence behind `gtm`.
- [mattpocock/skills](https://github.com/mattpocock/skills) (check its license file; used as-is via npx skills, not copied)

## More from Dobeu Tech Solutions

[Dobeu Tech Solutions LLC](https://dobeu.net) publishes other public projects:

- [StatMiner](https://github.com/Dobeu-tech-eco/statminer) ([live](https://statminer.vercel.app)): data-driven AI answers to complex questions.
- [DOT Copilot](https://github.com/Dobeu-tech-eco/DOT-Copilot) ([live](https://dot-copilot.vercel.app))
- [Super RAG MCP](https://github.com/Dobeu-tech-eco/super-rag-mcp): self-hosted RAG over local and cloud sources, exposed as an MCP server.
- [Claude Harness (minimal)](https://github.com/Dobeu-tech-eco/plugin-claudeharness): four-agent lead, builder, reviewer, verifier pipeline for Claude Code.
- [Dobeu v0 Skills Pack](https://github.com/Dobeu-tech-eco/dobeu-v0-skills-pack): a skills pack for v0.

## Support

Enjoyed it? Help us build the next one. We're a small development team: there's no paywall, and buying us a coffee is always welcome.

<!-- TODO(funding): add donation link -->
Donation link coming soon.

## Tests

Run the suite from the plugin folder: `cd plugins/dts2-harness && python3 -m unittest discover -s tests` (or `make test` from the repo root). `make doctor` checks git, Python, the claude CLI and sandbox tooling first. The property tests (`tests/test_hypothesis_*.py`) need Hypothesis, which is not part of the plugin runtime: run `pip install -r requirements-dev.txt` (ideally in a virtualenv) to enable them; without it they are skipped.

## License

Dobeu Source-Available License 1.0. Copyright Dobeu Tech Solutions LLC. See [LICENSE](LICENSE).

In short: you can install and use it (including at work), read it, change it for your own use, and share copies for free as long as the license and copyright notices stay with them. You can't sell it, put it in a paid product or hosted service, or relicense it without written permission. Dobeu can end the license with 30 days' notice. Versions released earlier under the MIT License stay MIT for the copies people already have. For commercial licensing, get in touch through [dobeu.net](https://dobeu.net).

## Changelog

Released versions are in [CHANGELOG.md](CHANGELOG.md). Changes not yet released are listed below.

## Unreleased
