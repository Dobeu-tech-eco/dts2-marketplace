# dts2-harness

Second-generation Dobeu Tech Solutions agent harness. It supersedes `harness@harness` (plugin-claudeharness) and `harness-ops`. Enable dts2 and disable those two so each agent exists once.

## What it adds over v1
| Need | How dts2 handles it |
|---|---|
| WSL and Linux | Python core scripts, bash hooks, PowerShell and bash installers. `env-detect.py` finds which Claude home is live, including the WSL wrapper that runs Windows `claude.exe`. |
| Plugins that keep coming back | `machine-prep` now finds plugins synced from your claude.ai account (loaded as `name@synced` on every start) and turns syncing off with `syncClaudeAiPlugins: false`, or disables them one by one if you keep a short list. It also flags repos whose settings re-enable plugins you turned off. |
| Scan, prune, set up a machine | `machine-prep` skill plus `auditor` agent and `scripts/machine-prep.py` (audit, plan, apply) driven by `profiles/blueprint.json` from agent-startup-blueprint. Prune means disable, with a settings backup first. |
| Many repos | `setup` skill in batch mode (one subagent per repo, in parallel) or workspace mode (`.harness-workspace.yaml` with contracts and release order). |
| Self-learning | `learn` skill keeps `.harness/lessons.md`. The SessionStart hook loads recent lessons into context; lead, builder, and reviewer read them every run. |
| Agent SDK and other agents | `sdk/dts2-run.py`: auth from env key, a key command you choose (for example an Anthropic CLI), or the existing Claude login. Optional Codex or Gemini second opinion. |
| Scale teams | `scout` sizes the job, `run` picks tier S/M/L/XL: up to 4 parallel builders on disjoint lanes, up to 4 reviewers by axis, git worktrees for large jobs. |

## Components
- Agents: lead, builder, fixer, reviewer, verifier, scout, auditor
- Skills: onboard, machine-prep, setup, run, learn, evolve, gtm, sdk, action-items, model, find-skills, check-in, ship, feature, autopilot, dpp, dpp-full, fullauto
- Hooks: SessionStart (lessons), Stop (typecheck and lint)
- Settings: `.claude/dts2-harness.local.md` (template in `templates/`)

## Parallel autopilot
| Skill | What it does |
| --- | --- |
| `dpp` | `/dts2-harness:dpp [dry-run]` plans lanes from the check-in list (`lanes.py plan` + feasibility `check`, `estimated_spend` per lane), gets approval, starts one headless autopilot son per lane in its own worktree, supervises (status, head-answered questions, two send-backs, second opinion), serialises merges with `merge-go.md`, rolls lessons up, and ends with `dpp-report.md` plus the task ledger. |
| `dpp-full` | `dpp --full`: a delegation scan adds sons' questions, parked items and new action items as lane candidates; continuous dispatch starts the next lane without asking. |
| `fullauto` | `dpp-full` with autopilot forced on, re-running check-in between rounds until nothing is outstanding and every lane is done or blocked with its items in the ledger. |

Model calls that the harness scripts start go through `scripts/model_call.py` (one machine-wide limit, `supervisor.max_model_calls`); Agent-tool seats (`dts2-harness:reviewer`) run inside the host session and cannot be gated by that limit. The `max_usd` cap covers Claude spend only: a call from a non-Claude CLI prints no cost, is counted as `unreported_calls` in `budget.json` and shown by `lanes.py budget`, and never stops a run. Full notes are in CHANGELOG.md under 3.10.0.

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

The provider that fills the lead, advisory and sign-off seats is selectable with `/dts2-harness:model` (default Claude); the rule holds whichever provider leads. If the lead hits a usage or token limit or stalls, the harness writes the handoff and fails over to the next eligible provider (`scripts/failover.py`). The pre-check before every run command (`scripts/skills-check.py`) keeps companion and keep-list skills installed and current, refreshes marketplaces, and upgrades the harness in place when a newer version is published (handoff first; the next run finishes the upgrade). `/dts2-harness:find-skills` is available any time to rescan the repo and suggest skills. Every detected agent gets a seeded project memory file (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) at scaffold.

## Settings
Copy `templates/dts2-harness.local.md` to `<repo>/.claude/dts2-harness.local.md`. Keys: `enabled`, `stop_checks`, `lessons_inject`, `lessons_max`, `auto_scale`, `max_builders`, `max_reviewers`, `use_worktrees`, `second_opinion`, `profile`, `max_execution_effort`, `delegation_strict`, `lead_provider`, `son_model` (the model every dpp son runs on; default `opus`). Restart Claude Code after editing.

## Known limits
- Login state for gemini, grok, muse, and opencode is self-reported by you; the harness cannot verify it.
- Impeccable and marketing-skills are external plugins. The harness uses them when installed and does not bundle them.
- Grok review and builder commands (`roster.py command`) were exercised on 2026-10-22; model ids stay marked unverified.
- Muse Code CLI flags and the `muse-spark-1.3` model id are unverified and user-editable.
- Effort levels beyond `medium` are verified only for claude and codex.
- The Sol 6.1 roster slot is user-editable; check it matches what you run.

## Acknowledgements
dts2-harness builds on patterns from these projects. We learned from them and wrote our own implementation; no code was copied.
- [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (MIT): the deep-interview pattern behind the end-state interview.
- [Impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0): the critique and polish pattern behind the finish pass.
- [marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT): the go-to-market sequence behind `gtm`.
- [mattpocock/skills](https://github.com/mattpocock/skills) (check its license file; used as-is via npx skills, not copied)

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

## Tests
Run the suite from the plugin folder: `cd plugins/dts2-harness && python3 -m unittest discover -s tests` (or `make test` from the repo root). `make doctor` checks git, Python, the claude CLI and sandbox tooling first. The property tests (`tests/test_hypothesis_*.py`) need Hypothesis, which is not part of the plugin runtime: run `pip install -r requirements-dev.txt` (ideally in a virtualenv) to enable them; without it they are skipped.

## Docs
- [docs/GUIDE.md](docs/GUIDE.md): how to talk to the harness, which command when, the head, son and council flow, and the 3.10.0 digest. Start here.
- [docs/INVENTORY.md](docs/INVENTORY.md): every skill, agent, hook, script and `lanes.py` subcommand with exact usage.
- [ARCHITECTURE.md](ARCHITECTURE.md): modules, state port, plan graph, briefs and hook entry points.
- [CHANGELOG.md](CHANGELOG.md): release notes.

## Changelog

Released versions are in [CHANGELOG.md](CHANGELOG.md). Changes not yet released are listed below.

## Unreleased

