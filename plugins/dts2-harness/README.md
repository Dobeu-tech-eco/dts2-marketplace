# dt: a harness for Claude Code

[![Dobeu Tech Solutions LLC](https://dobeu.net/brand/dobeu-horizontal.png)](https://dobeu.net)

A **Dobeu Tech Solutions LLC** product. The command stays `/dt:<command>`. The listing title is “dt by Dobeu: one task to a reviewed pull request.”

`dt` turns one task into a planned, built, reviewed and verified pull request, with you approving at the points that matter.

You describe the end state you want once. A scout sizes the job, a lead plans it, builders work in parallel on separate files, and reviewers and a verifier check the result. You get a pull request and a written receipt of what happened. It is made by [Dobeu Tech Solutions LLC](https://dobeu.net) and released under the Dobeu Source-Available License (see [License](#license)).

It is for developers and small teams who already use Claude Code and want a repeatable way to run larger changes: multi-file features, cross-repo work, roadmap backlogs, cleanup passes. If your task fits in one prompt, you do not need it. It never merges, pushes to a default branch or deploys without an approval that you write yourself.

## Install

Inside Claude Code:

```
/plugin marketplace add Dobeu-tech-eco/dts2-marketplace
/plugin install dt@dts2
```

Restart Claude Code (or run `/reload-plugins`), then run `/dt:onboard`. The plugin is named `dt`, so commands are `/dt:<command>` and roles are `dt:<role>`. The marketplace is named `dts2`.

If `claude` in WSL wraps the Windows `claude.exe`, both shells share the Windows Claude home. Install once from Windows. Install inside WSL only if you run the native Linux CLI there.

## Update and uninstall

Update:

```
/plugin marketplace update dts2
/reload-plugins
```

The check that runs before every run command also refreshes marketplaces and upgrades the plugin in place when a newer version is published. It writes a handoff first, and the next run finishes the upgrade.

Uninstall:

```
/plugin uninstall dt@dts2
/plugin marketplace remove dts2
```

Uninstalling leaves your repos alone. `.harness/` folders, `.claude/dts2-harness.local.md` and `~/.dts2/` stay until you delete them.

### Coming from dts2 or dts2-harness

The plugin used to be called `dts2` (before 4.0, `dts2-harness`). Commands are now `/dt:<command>`. Your settings and `.harness/` state are unchanged.

```
/plugin uninstall dts2@dts2
/plugin marketplace update dts2
/plugin install dt@dts2
/reload-plugins
```

On a version before 4.0 the installed plugin is `dts2-harness`. Run `/plugin uninstall dts2-harness@dts2` first.

## Requirements

- Claude Code with plugin support.
- Python 3.10 or newer (`python3`, `python`, or `py -3`). The scripts use only the standard library.
- `git` (2.38 or newer) and bash for the hooks. On Windows, Git Bash works, and Claude Code already uses it.
- The `gh` CLI, signed in, for anything that opens or sweeps pull requests (`ship`, `pr-sweep`, `dpp`, `autopilot`).
- Linux, macOS, WSL or Docker for parallel runs. On native Windows `dpp` parks with the reason `windows-native` (see [docs/RUNTIMES.md](docs/RUNTIMES.md)).
- Optional: `claude-agent-sdk` for the headless runner. Optional: the command-line tools for other AI providers (`codex`, `gemini`, `grok`, `opencode`, `copilot`, `muse`) if you want them on the roster. `autopilot` votes across three providers, so it needs three installed and signed in.

To check all of this on your machine, run `python3 scripts/doctor.py` from the plugin folder, or `make doctor` in a clone of the marketplace repo.

## Quick start

1. `/dt:onboard` explains the roles and commands and recommends where to start. It changes nothing until you pick.
2. `/dt:setup` (in a repo) interviews you until you approve an end state, then scaffolds `.harness/`. Pass several paths, or a workspace file, for a multi-repo project.
3. `/dt:run add rate limiting to the public API` plans the work. You answer `approve`, `edit` or `stop` at the plan, let it build, then answer again at the ship summary.
4. `/dt:check-in` shows progress against the end state, such as `3 of 8 complete`. It is read-only.
5. `/dt:action-items` lists secrets, decisions and handoffs that wait on you, each with the command that resolves it.

Optional first steps:

- `/dt:machine-prep` audits your installed plugins and MCP servers against a blueprint and disables overlap. It backs up your settings first and never deletes.
- `/dt:model` switches which provider leads (Claude by default).
- `/dt:composio`, `/dt:sdk`, `/dt:knowledge` and `/dt:gtm` set up optional integrations (see the table below).

Which command to use when: [docs/GUIDE.md](docs/GUIDE.md). Exact invocation of every command: [docs/COMMANDS.md](docs/COMMANDS.md).

## How it works

**Roles.** Eight roles do the work. Each has one job, and the one that builds never judges its own work.

| Role | Job |
|---|---|
| `scout` | Measures the repo and recommends a team size (tier S and up). Read-only. |
| `lead` | Splits the end state into tasks, each with its own set of files. Read-only. |
| `builder` | Implements one task inside the files it owns. Several run at once. |
| `reviewer` | Reviews the diff and returns findings by severity. Never edits. |
| `verifier` | Runs build, type, lint and test commands and checks for stubs. Never fixes. |
| `fixer` | Takes the second fix round on a failure, with fresh context. |
| `auditor` | Inventories your installed tooling for `/dt:machine-prep`. Read-only. |
| `incident-reviewer` | Finds a root cause for each open incident. Read-only. |

**Checkpoints.** A checkpoint is a question with the plan or the ship summary and the words `approve`, `edit` or `stop`. `/dt:run` asks you. `/dt:autopilot` replaces your answer with a vote across three providers.

**Lanes.** A lane is one stream of work on its own git branch and worktree (a separate checkout of the repo). `/dt:dpp` runs several lanes in parallel. A head session plans them, supervises them, merges them in order and writes one report. Each lane is run by a headless worker that commits but never pushes. The docs call these workers "sons".

**Receipts.** A receipt is the written record of a run: what was planned, built, checked and shipped. It is saved in `.harness/receipts/` and added to the pull request. Run records and receipts stay out of git.

**Lessons.** Reviewer findings become per-repo lessons in `.harness/lessons.md`. Later runs read them. `/dt:learn` consolidates them.

**Cost control.** The lead plans and signs off with a frontier model. Builders use the cheapest capable model and raise effort for harder work instead of switching to a pricier model. The receipt records a `Delegation policy` line, and the final review blocks on it. If the lead hits a usage limit or stalls, the harness writes a handoff and fails over to the next eligible provider.

Plugin contents:

- Roles: lead, builder, fixer, reviewer, verifier, scout, auditor, incident-reviewer
- Skills: onboard, composio, machine-prep, setup, run, learn, evolve, gtm, sdk, action-items, model, find-skills, check-in, ship, feature, autopilot, dpp, dpp-full, fullauto, ask-expert, repo-sweep, pr-sweep, fleet, cooldown, knowledge, incidents, steer
- Hooks: session start (lessons, cooldowns), prompt intake, pre-compact handoff, stop checks (typecheck and lint), merge guard, policy gate, PR receipt, context guard, role report check, action-items ledger, session end
- Settings: `.claude/dts2-harness.local.md` (template in `templates/`)

The full module map is in [ARCHITECTURE.md](ARCHITECTURE.md). Every skill, hook and script is listed in [docs/INVENTORY.md](docs/INVENTORY.md).

### Parallel lanes

| Skill | What it does |
| --- | --- |
| `dpp` | `/dt:dpp [dry-run]` plans lanes from the check-in list and estimates spend per lane. After you approve, it starts one headless worker per lane in its own worktree, supervises them (status, answers to questions, two send-backs, a second opinion), merges in order with `merge-go.md`, rolls lessons up, and ends with `dpp-report.md` and the task ledger. |
| `dpp-full` | `dpp --full`: also scans for workers' questions, parked items and new action items, adds them as lane candidates, and starts the next lane without asking. |
| `fullauto` | `dpp-full` with autopilot forced on. It re-runs check-in between rounds until nothing is outstanding and every lane is done or blocked. |

### Providers

One profile per provider lives in `profiles/agents/`. `tokenBurn` is a relative, user-editable weight, not a price or a quota. It only ranks providers for a role (lower is cheaper to run).

| Provider | Models (frontier / standard / economy) | Used for | tokenBurn (standard) | Effort support |
|---|---|---|---|---|
| claude | opus / sonnet / haiku | lead, verifier, builder, reviewer | 3 | low, medium, high, max |
| codex | gpt-6-astra / gpt-6.1-sol / gpt-6-luna | builder, second opinion | 3 | low, medium, high, xhigh (max and ultra only when requested; luna has no ultra) |
| gemini | gemini-2.5-pro / gemini-2.5-flash / gemini-2.5-flash-lite | builder, reviewer, second opinion (through the Antigravity `agy` CLI) | 2 | medium |
| grok | grok-4.7 / grok-4.7 / grok-4-fast | builder, reviewer, second opinion | 3 | medium |
| opencode | CLI default | builder | 2 | medium |
| copilot | CLI default | builder, security reviewer | 2 | medium |
| muse | muse-spark-1.3 on every tier | builder, second opinion (Meta's Muse Code terminal tool) | 2 | medium |
| cursor | IDE default | builder (handoff only, no dispatch) | 0 | medium |
| antigravity | IDE default | builder (handoff only, no dispatch) | 0 | medium |

Effort levels beyond `medium` are verified only for claude and codex. Every other row is a user-editable default. API-key providers (`claude-api`, `codex-api`, `grok-api`) are covered in [docs/API-AGENTS.md](docs/API-AGENTS.md).

## All commands

Every slash command in the plugin (27). Commands marked "never starts on its own" run only when you type them. Exact flags are in [docs/COMMANDS.md](docs/COMMANDS.md).

| Command | What it does | Example |
|---|---|---|
| **Getting started** | | |
| `/dt:onboard` | Tour of the plugin, its roles and commands, with optional Composio and extra-hooks steps at the end. Never starts on its own. | `/dt:onboard` |
| `/dt:machine-prep` | Audits installed plugins, tools and skills, then disables overlap (never deletes; settings backed up first). Never starts on its own. | `/dt:machine-prep` |
| `/dt:composio` | Optional Composio setup: connects your account, maps toolkits, offers to disable tools Composio already covers. Never starts on its own. | `/dt:composio` |
| `/dt:setup` | Interviews you until the end state is approved, then scaffolds `.harness/` for one repo, several repos or a workspace. | `/dt:setup` or `/dt:setup --scaffold-only` |
| `/dt:model` | Chooses which provider (Claude, Codex, Gemini) leads, advises and signs off; adds and renames roster providers. Never starts on its own. | `/dt:model` |
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
| `/dt:dpp-full` | `dpp` that also fills lanes from a backlog scan and keeps dispatching. Never starts on its own. | `/dt:dpp-full` |
| `/dt:fullauto` | `dpp-full` looping until nothing is outstanding, within budget and stall guards. Never starts on its own. | `/dt:fullauto` |
| `/dt:sdk` | Sets up headless runs with the Claude Agent SDK for CI, cron or servers. Never starts on its own. | `/dt:sdk` |
| `/dt:cooldown` | Pauses a provider that hit a usage limit until it resets; shared by every session on the machine. | `/dt:cooldown set codex 2d` |
| **Status and memory** | | |
| `/dt:check-in` | Read-only progress against the end state, `N of M complete`; `all` covers every session on this computer. | `/dt:check-in`, `/dt:check-in all` |
| `/dt:action-items` | What is waiting on a person (secrets, decisions, handoffs, deploys), with the command that resolves each. | `/dt:action-items` |
| `/dt:fleet` | Lists every dt session on this computer and broadcasts a note, handoff or pause to them. | `/dt:fleet` |
| `/dt:incidents` | Misfires recorded by hooks (hung spawns, missing reports), what is running now, and a root-cause review of open incidents. | `/dt:incidents review` |
| `/dt:learn` | Turns reviewer findings into per-repo lessons later runs read. | `/dt:learn promote L-012` |
| `/dt:knowledge` | Your private, synced store of preferences and terms across devices. Never stores secrets. Never starts on its own. | `/dt:knowledge setup` |
| **Maintenance** | | |
| `/dt:find-skills` | Rescans the repo and recommends a ranked set of skills, hooks, MCP servers and other tooling; adds only your picks. | `/dt:find-skills` |
| `/dt:ask-expert` | Reviews one repo and returns a keep, fold, template, archive or delete memo with a scorecard. Changes nothing. | `/dt:ask-expert my-old-repo` |
| `/dt:repo-sweep` | A quick ask-expert pass on every repo of an owner, then one cleanup screen. Delete is never bulk. | `/dt:repo-sweep Dobeu-tech-eco` |
| `/dt:evolve` | Changes the plugin at its source repo: edit, test, bump the version, commit. Pushes only on your yes. For maintainers. | `/dt:evolve` |

## Configuration

### Per-repo settings

Copy `templates/dts2-harness.local.md` to `<repo>/.claude/dts2-harness.local.md` and edit the keys you want. The file is not committed. Restart Claude Code after editing.

| Key | Default | What it does |
|---|---|---|
| `enabled` | `true` | Turns the plugin's hooks on or off for this repo. |
| `stop_checks` | `true` | Runs typecheck and lint when a turn stops. |
| `stop_checks_block` | `false` | A red stop check blocks the stop once (never twice in a row). |
| `lessons_inject` | `true` | Feeds saved lessons to new sessions. |
| `lessons_max` | `5` | How many lessons to feed. |
| `pr_receipt_template_push` | `false` | Lets the PR-receipt hook commit and push the PR template to the PR branch. |
| `auto_scale` | `true` | Sizes the team from the scout's tier. |
| `max_builders` | `4` | Cap on builders that write files. |
| `max_reviewers` | `4` | Cap on parallel reviewers. |
| `continuous_dispatch` | `true` | Keeps builders in flight while ready sections exist; parks stalled ones. |
| `builder_timeout_min` | `20` | Minutes without a builder report before it is parked. |
| `son_permission_mode` | `dontAsk` | Permission mode for `dpp` workers: `dontAsk`, `acceptEdits`, `plan` or `default`. `bypassPermissions` is refused. |
| `mailbox_wait_min` | `30` | Minutes a `dpp` worker waits for the head's answer before it parks. |
| `dpp_full_ask_each_lane` | `true` | `dpp-full` outside autopilot asks before each new lane. |
| `fullauto_freeze_scope` | `true` | `fullauto` freezes the approved item set at its first plan. |
| `post_merge_fix_attempts` | `2` | Post-merge fixes per lane before a revert PR opens. |
| `son_model` | `sonnet` | Model every `dpp` worker runs on. Set `opus` per task for hard lanes. |
| `use_worktrees` | `auto` | `auto`, `always` or `never`. One worktree per builder in a git repo. |
| `second_opinion` | `none` | `none`, `codex` or `gemini`. |
| `profile` | `blueprint` | Blueprint file under `profiles/`, or a path, used by `machine-prep`. |
| `end_state_threshold` | `80` | Clarity score the end-state interview must reach. |
| `auto_learn` | `true` | Runs `learn` after the ship checkpoint. |
| `context_guard` | `true` | Stops a run and re-runs setup on a context spike. |
| `context_guard_tool_calls` | `250` | Tool calls in a session before the guard fires. |
| `context_guard_mb` | `12` | Transcript size in MB before the guard fires. |
| `context_guard_stop` | `false` | The guard also ends the turn instead of only advising. |
| `policy_gate` | `true` | The policy hook (see Safety and limits). |
| `max_execution_effort` | `high` | Cap on builder effort (`low`, `medium`, `high`, `max`). |
| `delegation_strict` | `true` | Blocks ship if any builder ran a frontier model. |
| `lead_provider` | `claude` | Provider that leads, advises and signs off. Set it with `/dt:model`. |

Two more keys are documented in [docs/GUIDE.md](docs/GUIDE.md): `intake: false` turns off the prompt queue, and `autonomy: unattended` enables unattended mode.

Budgets, spend caps, council, merge target, shared files and the roster live in `<repo>/.harness/config.yaml`. See `templates/config-supervisor.yaml`.

Approvals are not a setting. They are a top-level `dts2_approvals` key in `.claude/settings.local.json`, for example `{"dts2_approvals": {"merge": ["42"]}}`. Only a person edits that file, and `scripts/approvals.py` reads nothing else. The kinds are `recorded_yes`, `unsafe_no_sandbox`, `blocked_pr_done`, `lane_override` and `merge`. A merge that deploys production (`merge: deploys_production: true` in `.harness/config.yaml`) needs its PR number there.

### Environment variables

| Variable | What it does | Sensitive |
|---|---|---|
| `DTS2_BIN_AGY` | Full path to the `agy` binary (Gemini through Antigravity) when it is off your PATH. | No |
| `DTS2_BIN_GROK` | Full path to the `grok` binary when it is off your PATH. | No |
| `DTS2_UNATTENDED` | Set to `1` to enable unattended mode, same as `autonomy: unattended`. | No |
| `DTS2_KNOWLEDGE_TOKEN` | Token for the Cloudflare knowledge backend of `/dt:knowledge`. | Yes |
| `DTS2_PR_RECEIPT_KEY_FILE` | Path to the key file that signs receipts. The hook fails closed if the file is unreadable or empty. | Yes (the file) |

Keep secrets out of chat, repos and the roster file. Secrets never go into logs or action items, and missing variables are recorded by name only. For API-key providers, store the key in your keyring and reference it with `apiKeyRef` (see [docs/API-AGENTS.md](docs/API-AGENTS.md)).

### Where things live

| Location | What it holds |
|---|---|
| `<repo>/.claude/dts2-harness.local.md` | Per-repo settings. |
| `<repo>/.harness/end-state.md` | The approved end state every run is measured against. |
| `<repo>/.harness/config.yaml` | Budgets, council, merge target, shared files, timeouts. |
| `<repo>/.harness/` (the rest) | Lessons, state, handoff, action items, receipts, run records. |
| `<repo>/.claude/settings.local.json` | Your approvals under `dts2_approvals`. |
| `~/.dts2/` | Machine-wide state: fleet registry, cooldowns, Composio map, repo backups, knowledge store. |

## Safety and limits

What it does without asking: the hooks run as soon as the plugin is installed, each honoring `enabled`. Extra hooks (command guard, auto-format, tests on stop, notifications, database guards) are added only when you pick them in the last step of `/dt:onboard`, with a backup and a dry run first.

What it will not do without you:

- **Merge or push to a protected branch.** The merge guard blocks `gh pr merge` and default-branch pushes unless you add the PR to `dts2_approvals` (or, under `dpp`, the head writes `merge-go.md`). `/dt:ship` never merges. Refusals are logged in `.harness/merge-guard.log`.
- **Run risky commands.** The policy gate denies force-push, `--admin`, deploy CLIs, `gh secret`, `vercel env` and a bare `env`, for the head session and every worker.
- **Approve itself.** Workers cannot write `dts2_approvals`. Under `dpp`, workers commit a branch, and only the head pushes and opens PRs.
- **Delete.** `/dt:machine-prep` disables and never deletes. `/dt:repo-sweep` never deletes in bulk. `/dt:evolve` pushes only on your yes.
- **Update companion skills.** Skills pinned in `.harness/keep.yaml` stay put without your explicit yes. `npx skills update` never runs; updates arrive as proposals in `.harness/skill-updates.json`.

Tradeoffs:

- Model calls that the harness scripts start go through `scripts/model_call.py` (one machine-wide limit, `supervisor.max_model_calls`). Agent-tool seats (`dt:reviewer`) run inside the host session and cannot be gated by that limit.
- The `max_usd` cap covers Claude spend only. A call from another provider's CLI prints no cost, is counted as `unreported_calls` in `budget.json`, shows in `lanes.py budget`, and never stops a run.
- Login state for gemini, grok, muse and opencode is self-reported by you. The harness cannot verify it.
- Impeccable and marketing-skills are separate plugins. The harness uses them when installed and does not bundle them.
- Grok review and builder commands (`roster.py command`) were exercised on 2026-10-22. Model ids stay marked unverified.
- Muse Code CLI flags and the `muse-spark-1.3` model id are unverified and user-editable.
- The Sol 6.1 roster slot is user-editable. Check it matches what you run.

## Troubleshooting

Run `python3 scripts/doctor.py` first. It reports Python, git, the `claude` CLI, sandbox tools, the auth method (named, never the value) and the platform. Add `--json` for machine-readable output.

- **`/dt:` commands do not appear.** Restart Claude Code or run `/reload-plugins`, then check that `/plugin` shows `dt` as enabled.
- **Every role shows up twice.** An older `harness`, `harness-ops` or `dts2` copy is still enabled. Disable it under `/plugin`, Installed, or run `/dt:machine-prep`.
- **Settings changes do nothing.** Edits to `.claude/dts2-harness.local.md` need a Claude Code restart.
- **A merge or push was denied.** The policy gate or the merge guard is working as designed. Add your approval under `dts2_approvals` in `.claude/settings.local.json` and see `.harness/merge-guard.log`. Details: [docs/GUIDE.md](docs/GUIDE.md).
- **`dpp` parks with `windows-native`.** Parallel lanes need POSIX signals. Run under WSL or Docker ([docs/RUNTIMES.md](docs/RUNTIMES.md)).
- **A run stopped midway, or a provider hit a usage limit.** `/dt:check-in` shows what is outstanding, `/dt:action-items` shows what waits on you, and `/dt:run resume` continues from the handoff file. `/dt:cooldown set <provider> <date or duration>` skips a limited provider everywhere until it resets.
- **WSL cannot find your Claude settings.** If `claude` in WSL wraps `claude.exe`, the Windows home is the live one. `python3 scripts/env-detect.py` shows which.

## Documentation

- [docs/GUIDE.md](docs/GUIDE.md): how to talk to the harness, which command when, the head, worker and council flow. Start here.
- [docs/COMMANDS.md](docs/COMMANDS.md): the command reference, with exact invocation and what each command writes.
- [docs/INVENTORY.md](docs/INVENTORY.md): every skill, role, hook, script and `lanes.py` subcommand.
- [docs/API-AGENTS.md](docs/API-AGENTS.md) and [docs/RUNTIMES.md](docs/RUNTIMES.md): API-key providers; Windows, WSL and Docker.
- [ARCHITECTURE.md](ARCHITECTURE.md): modules, state port, plan graph, briefs and hook entry points.

## Development

Run the suite from the plugin folder:

```
cd plugins/dts2-harness
python3 -m unittest discover -s tests
```

From the repo root, `make test` does the same and `make doctor` checks git, Python, the `claude` CLI and sandbox tooling first. The property tests (`tests/test_hypothesis_*.py`) need Hypothesis, which is not part of the plugin runtime. Run `pip install -r requirements-dev.txt` (ideally in a virtualenv) to enable them. Without it they are skipped.

## Acknowledgements

dt builds on patterns from these projects. We learned from them and wrote our own implementation. No code was copied. Publishers, licenses, and the skills each one covers are listed in [skills-bundled](../../skills-bundled/README.md).

- [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (MIT, Yeachan Heo): the deep-interview pattern behind the end-state interview.
- [Impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0, Paul Bakaus): the critique and polish pattern behind the finish pass.
- [marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Corey Haines): the go-to-market sequence behind `gtm`.
- [mattpocock/skills](https://github.com/mattpocock/skills) (MIT, Matt Pocock): companion skills installed into the project with `npx skills add`, not copied into this plugin.
- [warpdotdev/common-skills](https://github.com/warpdotdev/common-skills) (MIT, Denver Technologies, Inc.): `resolve-merge-conflicts`.
- [obra/superpowers](https://github.com/obra/superpowers) (MIT, Jesse Vincent): the `test-driven-development` skill recommended by slug.
- [wshobson/agents](https://github.com/wshobson/agents) (MIT, Seth Hobson): the database skills recommended by slug.
- [anthropics/skills](https://github.com/anthropics/skills/tree/main/skills/frontend-design) (Apache-2.0 on `frontend-design`): the frontend skill recommended by slug.

## Changelog

Released versions are in [CHANGELOG.md](CHANGELOG.md). Changes not yet released are listed below. The list is empty right after a release.

## Unreleased

## License

Dobeu Source-Available License 1.0. Copyright Dobeu Tech Solutions LLC. See [LICENSE](LICENSE).

In short: you can install and use it (including at work), read it, change it for your own use, and share copies for free as long as the license and copyright notices stay with them. You can't sell it, put it in a paid product or hosted service, or relicense it without written permission. Dobeu Tech Solutions can end the license with 30 days' notice. Versions released earlier under the MIT License stay MIT for the copies people already have. For commercial licensing, get in touch through [dobeu.net](https://dobeu.net).

## Support

Questions and bug reports: open an issue at [github.com/Dobeu-tech-eco/dts2-marketplace/issues](https://github.com/Dobeu-tech-eco/dts2-marketplace/issues).

We are a small development team. There is no paywall. Questions and commercial licensing go through [dobeu.net](https://dobeu.net).

Company policies, which control dobeu.net and the client portal: [Privacy](https://dobeu.net/privacy), [Terms](https://dobeu.net/terms), [Cookies](https://dobeu.net/cookies), [Marketing opt-out](https://dobeu.net/marketing-opt-out). What this plugin does with data on your machine is in [PRIVACY.md](../../PRIVACY.md).
