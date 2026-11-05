# dts2 marketplace

Claude Code plugin marketplace for Dobeu Tech Solutions.

| Plugin | What it does |
|---|---|
| [`dts2`](plugins/dts2-harness) | Plan-build-review-verify agent harness: end-state interview, Plan and Ship checkpoints, agent roster, deployment verification, GTM, machine prep, multi-repo scaffolding, lessons memory, and a headless Agent SDK runner. Windows, WSL, Linux, macOS. |

## What's new in 3.11.0
- Head policy gate: `hooks/policy-gate.sh` and `templates/policy.json` deny force-push, `--admin`, deploy CLIs, `gh secret` and `vercel env` for the head and every son; merges and default-branch pushes need a human approval kept in `.claude/settings.local.json`.
- Son containment and lifecycle: sons commit a branch and the head publishes, opens and merges the PR (`lanes.py publish`); protected paths, a head/son mailbox with deadlines, stuck-loop detection, `lanes.py wait`, and a plugin version-skew check before every son start.
- Merge safety and scope: base health and a merge mutex gate `merge-go` and `merge-go-step`; a capped post-merge fix then one revert PR; `override`, `dpp_full_ask_each_lane` and `fullauto_freeze_scope`.
- Agent gates, A/B eval runner (`--runs`, `--arm-b-env`), run-wide report sections, signed receipts, and a docs refresh (`docs/INVENTORY.md` now lists the lanes modules, templates and settings keys).
- Full notes: [CHANGELOG.md](plugins/dts2-harness/CHANGELOG.md).

## What's new in 3.10.0
- Parallel autopilot hardening: a 35-subcommand lane lifecycle in `lanes.py` (leases with TTL and epochs, `transition`, `merge-order`, `merge-go`, `merge-done`, `shutdown`, `reconcile`), a per-run merge journal and typed run records.
- Son containment: sandboxed headless sons with tool allowlists, an allowlisted environment, hard caps on turns, spend and model calls, and a merge guard hook that lets nothing merge without a `merge-go.md`.
- Council hardening (seat swap, blind and fenced ballots), a checks gate before any vote, a plan gate and builder audit, a `fixer` agent, production-readiness scaffolding, and `docs/INVENTORY.md` with a completeness test.
- Agent guide: [docs/GUIDE.md](plugins/dts2-harness/docs/GUIDE.md) explains how to talk to the harness, which command to use when, and the head, son and council flow.

## What's new in 3.9.0
- Parallel autopilot: `dpp`, `dpp-full` and `fullauto` run several autopilot lanes as headless sons under a head that plans, supervises and serialises merges.

## What's new in 3.8.0
- Autopilot council: after three failed voting rounds, five frontier seats read the step's full history and vote; Fable 5.1 heads the council and must answer every dissent.

## What's new in 3.7.0
- Pre-check before every run command, `ship` (user-initiated PR with sweep), `feature` (roadmap a feature), and `autopilot` (no human checkpoints behind a three-provider gate).

## What's new in 3.6.1
- Gtm is self-sufficient: auto-installs marketing-skills, runs a deep-dive (optional deep-interview re-run), selects the applicable skills, and runs them as one seamless pass.

## What's new in 3.6.0
- Strict delegation: frontier models only for advisory and sign-off, builders run the cheapest capable model at a complexity-scaled effort; Muse delegation fields (`effortLevels`, `tokenBurn`) join every profile.
- Automatic in-place upgrades from the pre-check (no separate upgrade command), `/dts2:model` (selectable lead provider), and lead failover on a stall that prefers verified providers.
- Per-agent project memory, `/dts2:find-skills`, `/dts2:check-in`, and companion-skill hooks (improve-codebase-architecture before tests, diagnosing-bugs at the fix cap, loop-me, setup-pre-commit, code-review).

## What's new in 3.5.0
- muse joins the roster as a builder and second opinion (never a review seat), and every agent seat gets its own headless command from `roster.py command`.
- `roster.py classify`: a billing or quota answer drops an agent for the run, and copilot's security seat falls back to grok.

## What's new in 3.0.0
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

## Skills
| Skill | Use it to |
|---|---|
| `onboard` | Explain the harness, its agents and skills, and where to start. Explanation only. |
| `machine-prep` | Scan the computer, prune plugins to the blueprint keep-set, set up the slim startup. Once per machine. |
| `setup` | Interview to an approved end state, then scaffold `.harness/` in one repo, many repos, or a multi-repo workspace. |
| `run` | Do a task: scout sizes it, lead plans, builders build, reviewers and verifier check, with Plan and Ship checkpoints. |
| `learn` | Turn reviewer findings into lessons that every future run reads. |
| `evolve` | Change the harness itself in its source repo: edit, validate, test, bump both manifests, commit. |
| `gtm` | Go-to-market in one pass through the `marketing-skills` plugin, ending in a `readiness.md` scorecard. |
| `sdk` | Run the same pipeline headless with the Agent SDK. |
| `action-items` | List open secrets, decisions, handoffs, and deploy steps with the command that resolves each. |
| `ship` | Open a PR on your own initiative: pre-checks, review, receipt, PR template, then tidy PRs and branches down to main and dev. |
| `feature` | Add a feature to the roadmap; deep interview when unclear; every plan doc updated; PR. |
| `autopilot` | Run steps unattended behind a 3-provider frontier consensus gate (Fable 5.1 tiebreak); one merged PR per step. |
| `model` | Pick which agent provider leads the lead, advisory and sign-off seats (`/dts2:model`); builders always run the cheapest capable model. |
| `find-skills` | Available any time (`/dts2:find-skills`): rescan the repo, ask a few questions, suggest skills, wire in the ones you pick. |
| `check-in` | Available any time (`/dts2:check-in`): a read-only checklist from where the project started through the approved end state, each item complete or outstanding. |
| `dpp` | Run several autopilot lanes in parallel as headless sons, one worktree each, under a head that plans, supervises and serialises merges (`dpp [dry-run] [--full] [resume]`). |
| `dpp-full` | `dpp --full`: also fills lanes from a delegation scan and keeps dispatching without a new approval. |
| `fullauto` | `dpp-full` with autopilot forced on, looping check-in until nothing is outstanding. |

Seven agents: lead, builder, fixer, reviewer, verifier, scout, auditor.

Not sure which command to use? Read the [agent guide](plugins/dts2-harness/docs/GUIDE.md): how to talk to the harness, a which-command-when table, and the head, son and council flow.

## Install
Inside Claude Code:

```
/plugin marketplace add Dobeu-tech-eco/dts2-marketplace
/plugin install dts2@dts2
```

Then turn off older copies so agents are not duplicated: `/plugin`, Installed, disable `harness` and `harness-ops` if present. Or run `/dts2:machine-prep`, which does it with a settings backup.

Restart Claude Code and run `/dts2:onboard`.

## Migrating from dts2-harness

The plugin is now named `dts2`: commands are `/dts2:<command>`, agents `dts2:<agent>`.
```
/plugin uninstall dts2-harness@dts2
/plugin marketplace update dts2
/plugin install dts2@dts2
/reload-plugins
```
Settings (`.claude/dts2-harness.local.md`) and `.harness/` state are unchanged.

## Update

```
/plugin marketplace update dts2
```

## WSL note

If your WSL `claude` command wraps the Windows `claude.exe`, both shells share the Windows Claude home. Install once from Windows. Install inside WSL only when you run the native Linux CLI there.

## Known limits
- Login state for gemini, grok, muse, and opencode is self-reported by you; the harness cannot verify it.
- Impeccable and marketing-skills are external plugins. The harness uses them when installed and does not bundle them.
- Grok review and builder commands (`roster.py command`) were exercised on 2026-10-22; model ids stay marked unverified.
- The Sol 6.1 roster slot is user-editable; check it matches what you run.

## Acknowledgements
dts2-harness builds on patterns from these projects. We learned from them and wrote our own implementation; no code was copied.
- [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (MIT): the deep-interview pattern behind the end-state interview.
- [Impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0): the critique and polish pattern behind the finish pass.
- [marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT): the go-to-market sequence behind `gtm`.

## License

MIT
