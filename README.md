# Dobeu marketplace for Claude Code (`dts2`)

A Claude Code plugin marketplace from [Dobeu Tech Solutions LLC](https://dobeu.net). It currently carries one plugin: **dt**, a harness that takes a task from plan to build to review to verified pull request, with you approving at the points that matter.

| Plugin | What it does |
|---|---|
| [`dt`](plugins/dts2-harness) | Plan, build, review and verify agent harness: an end-state interview, Plan and Ship checkpoints, parallel lanes, deployment verification, lessons memory and a headless Agent SDK runner. Windows, WSL, Linux, macOS. |

## Why it exists

A single Claude Code prompt handles a small edit well. Bigger changes drift, agents grade their own homework, parallel agents collide on files, and a session that ends takes its context with it. `dt` answers each of those:

- You approve an **end state** once; `/dt:check-in` shows `N of M complete` against it at any time.
- **Separate agents** plan (lead), build (builders on disjoint files), review (reviewers) and verify (verifier). Builders never review themselves.
- **Checkpoints** pause for your `approve`, `edit` or `stop` at the plan and before shipping. Every run ends with a receipt and a PR; nothing merges or deploys unless you have approved it.
- **Parallel lanes** (`/dt:dpp`) give each lane its own git worktree and serialise merges.
- A **handoff file** lets any agent resume where the last one stopped.
- **Cost discipline:** frontier models advise and sign off; builders use the cheapest capable model.

It is for developers and small teams already using Claude Code who want a repeatable way to run larger changes. Single-file fixes do not need it.

## Requirements

Claude Code with plugin support, Python 3.10 or newer, bash and `git`, plus the `gh` CLI for anything that opens pull requests. Parallel runs need Linux, macOS, WSL or Docker. Other agent CLIs (codex, gemini, grok, opencode, copilot, muse) are optional. Details: [plugin README](plugins/dts2-harness/README.md#requirements).

## Install

Inside Claude Code:

```
/plugin marketplace add Dobeu-tech-eco/dts2-marketplace
/plugin install dt@dts2
```

Then turn off older copies so agents are not duplicated: `/plugin`, Installed, disable `harness` and `harness-ops` if present. Or run `/dt:machine-prep`, which does it with a settings backup.

Restart Claude Code and run `/dt:onboard`.

## Wire it up

1. `/dt:onboard` explains the agents and skills and offers optional extra hooks (command guard, auto-format, tests on stop, notifications). Nothing is written until you pick.
2. `/dt:machine-prep` (once per machine) audits your plugins and MCP servers and disables the overlap, with a backup.
3. In a repo, `/dt:setup` interviews you to an approved end state and scaffolds `.harness/`. Per-repo settings live in `.claude/dts2-harness.local.md` (template: `plugins/dts2-harness/templates/dts2-harness.local.md`).
4. Optional: `/dt:model` to change which provider leads, `/dt:composio` to connect Composio, `/dt:sdk` for headless runs in CI, `/dt:knowledge` for a private preference store.

The full wiring guide, a table of where every config file lives, and troubleshooting are in the [plugin README](plugins/dts2-harness/README.md).

## Day to day

| You want to | Run |
|---|---|
| Do one task with checkpoints | `/dt:run <task>` (continue with `/dt:run resume`) |
| Plan a feature without building it | `/dt:feature <idea>` |
| Redirect work in progress | `/dt:steer <new direction>` |
| Open a PR for your branch | `/dt:ship` |
| Clear open and stale PRs | `/dt:pr-sweep` |
| See progress against the end state | `/dt:check-in` |
| See what is waiting on you | `/dt:action-items` |
| Work many items unattended | `/dt:autopilot <steps>`, `/dt:dpp` |

Not sure which command to use? Read the [guide](plugins/dts2-harness/docs/GUIDE.md): how to talk to the harness, a which-command-when table, and the head, son and council flow. Exact invocation of every command is in the [command reference](plugins/dts2-harness/docs/COMMANDS.md); every skill, agent, hook and script is in the [inventory](plugins/dts2-harness/docs/INVENTORY.md).

The harness has 27 skills (slash commands) and 8 agents: lead, builder, fixer, reviewer, verifier, scout, auditor and incident-reviewer.

## Update and uninstall

```
/plugin marketplace update dts2
/reload-plugins
```

To remove it: `/plugin uninstall dt@dts2`, then `/plugin marketplace remove dts2`. Your repos' `.harness/` folders and `~/.dts2/` are left in place.

## Migrating from dts2 or dts2-harness

The plugin is now named `dt`: commands are `/dt:<command>`, agents `dt:<agent>`. The marketplace keeps the name `dts2`.
```
/plugin uninstall dts2@dts2
/plugin marketplace update dts2
/plugin install dt@dts2
/reload-plugins
```
On a version before 4.0 the installed plugin is `dts2-harness`: run `/plugin uninstall dts2-harness@dts2` first. Settings (`.claude/dts2-harness.local.md`) and `.harness/` state are unchanged.

## WSL note

If your WSL `claude` command wraps the Windows `claude.exe`, both shells share the Windows Claude home. Install once from Windows. Install inside WSL only when you run the native Linux CLI there.

## Known limits

- Login state for gemini, grok, muse, and opencode is self-reported by you; the harness cannot verify it.
- Impeccable and marketing-skills are external plugins. The harness uses them when installed and does not bundle them.
- Grok review and builder commands (`roster.py command`) were exercised on 2026-10-22; model ids stay marked unverified.
- The Sol 6.1 roster slot is user-editable; check it matches what you run.

## Release highlights

Full notes for every release are in the [CHANGELOG](plugins/dts2-harness/CHANGELOG.md). Older highlights:

### What's new in 5.1.0
- Agent profiles with custom names (`claude-api`, `codex-api`, `grok-api`), per-agent rules enforced at dispatch, launch and tool time, a spend ledger, environment isolation and speed defaults.

### What's new in 5.0.0
- The plugin is renamed `dt`: commands are `/dt:<command>`, agents `dt:<agent>`. The marketplace keeps the name `dts2`.

### What's new in 3.11.0
- Head policy gate: `hooks/policy-gate.sh` and `templates/policy.json` deny force-push, `--admin`, deploy CLIs, `gh secret` and `vercel env` for the head and every son; merges and default-branch pushes need a human approval kept in `.claude/settings.local.json`.
- Son containment and lifecycle: sons commit a branch and the head publishes, opens and merges the PR (`lanes.py publish`); protected paths, a head/son mailbox with deadlines, stuck-loop detection, `lanes.py wait`, and a plugin version-skew check before every son start.
- Merge safety and scope: base health and a merge mutex gate `merge-go` and `merge-go-step`; a capped post-merge fix then one revert PR; `override`, `dpp_full_ask_each_lane` and `fullauto_freeze_scope`.
- Agent gates, A/B eval runner (`--runs`, `--arm-b-env`), run-wide report sections, signed receipts, and a docs refresh (`docs/INVENTORY.md` now lists the lanes modules, templates and settings keys).
- Full notes: [CHANGELOG.md](plugins/dts2-harness/CHANGELOG.md).

### What's new in 3.10.0
- Parallel autopilot hardening: a 35-subcommand lane lifecycle in `lanes.py` (leases with TTL and epochs, `transition`, `merge-order`, `merge-go`, `merge-done`, `shutdown`, `reconcile`), a per-run merge journal and typed run records.
- Son containment: sandboxed headless sons with tool allowlists, an allowlisted environment, hard caps on turns, spend and model calls, and a merge guard hook that lets nothing merge without a `merge-go.md`.
- Council hardening (seat swap, blind and fenced ballots), a checks gate before any vote, a plan gate and builder audit, a `fixer` agent, production-readiness scaffolding, and `docs/INVENTORY.md` with a completeness test.
- Agent guide: [docs/GUIDE.md](plugins/dts2-harness/docs/GUIDE.md) explains how to talk to the harness, which command to use when, and the head, son and council flow.

### What's new in 3.9.0
- Parallel autopilot: `dpp`, `dpp-full` and `fullauto` run several autopilot lanes as headless sons under a head that plans, supervises and serialises merges.

### What's new in 3.8.0
- Autopilot council: after three failed voting rounds, five frontier seats read the step's full history and vote; Fable 5.1 heads the council and must answer every dissent.

### What's new in 3.7.0
- Pre-check before every run command, `ship` (user-initiated PR with sweep), `feature` (roadmap a feature), and `autopilot` (no human checkpoints behind a three-provider gate).

### What's new in 3.6.1
- Gtm is self-sufficient: auto-installs marketing-skills, runs a deep-dive (optional deep-interview re-run), selects the applicable skills, and runs them as one seamless pass.

### What's new in 3.6.0
- Strict delegation: frontier models only for advisory and sign-off, builders run the cheapest capable model at a complexity-scaled effort; Muse delegation fields (`effortLevels`, `tokenBurn`) join every profile.
- Automatic in-place upgrades from the pre-check (no separate upgrade command), `/dt:model` (selectable lead provider), and lead failover on a stall that prefers verified providers.
- Per-agent project memory, `/dt:find-skills`, `/dt:check-in`, and companion-skill hooks (improve-codebase-architecture before tests, diagnosing-bugs at the fix cap, loop-me, setup-pre-commit, code-review).

### What's new in 3.5.0
- muse joins the roster as a builder and second opinion (never a review seat), and every agent seat gets its own headless command from `roster.py command`.
- `roster.py classify`: a billing or quota answer drops an agent for the run, and copilot's security seat falls back to grok.

### What's new in 3.0.0
- End-state interview: `setup` asks rounds on repos, agents, and skills until you approve the end state.
- Plan and Ship checkpoints: `run` pauses for approval twice and writes a PR receipt at ship.
- Rule 8, harness discipline: agents follow the harness rules instead of improvising around them.
- Agent roster: claude, codex, gemini, grok, opencode, and copilot, with subscription-first auth and cost tiers (cheapest capable agent first).
- Finish passes: an Impeccable-style critique and polish pass for UI, and a code finish pass.
- Deployment verification: detects the deploy target, verifies the live result, and offers a build-a-production and troubleshoot round.
- `action-items`: open secrets, decisions, and handoffs in one list, plus a pass-off file (`.harness/handoff/latest.md`) any agent can resume with `run resume`.
- `learn`: auto mode, metrics, and harness lessons.
- `gtm`: go-to-market in one pass through the `marketing-skills` plugin, ending in a readiness scorecard.
- `machine-prep` tiers: graded keep and prune levels with redundancy checks.
- `evolve`: change the harness in its source repo, validate, test, bump, commit.

## Acknowledgements

dt builds on patterns from these projects. We learned from them and wrote our own implementation; no code was copied.
- [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (MIT): the deep-interview pattern behind the end-state interview.
- [Impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0): the critique and polish pattern behind the finish pass.
- [marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT): the go-to-market sequence behind `gtm`.

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

## License

MIT. Copyright Dobeu Tech Solutions LLC. See [LICENSE](LICENSE).
