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
| Scale teams | `scout` sizes the job, `run` picks tier S/M/L/XL: up to 6 parallel builders on disjoint lanes, up to 4 reviewers by axis, git worktrees for large jobs. |

## Components
- Agents: lead, builder, reviewer, verifier, scout, auditor
- Skills: onboard, machine-prep, setup, run, learn, evolve, gtm, sdk, action-items, upgrade, model, find-skills, check-in
- Hooks: SessionStart (lessons), Stop (typecheck and lint)
- Settings: `.claude/dts2-harness.local.md` (template in `templates/`)

## Agent roster
One profile per agent in `profiles/agents/`. `tokenBurn` is a relative, user-editable weight, not a price or a quota; it only ranks agents for a seat (lower is cheaper to run). Effort support beyond `medium` is verified only for claude and codex; every other row is a user-editable default.

| Agent | Models (frontier / standard / economy) | Roles and specialization | tokenBurn (standard) | Effort support |
|---|---|---|---|---|
| claude | opus / sonnet / haiku | lead, verifier, builder, reviewer; plans, signs off and reviews | 3 | low, medium, high, max |
| codex | gpt-5-codex / gpt-5-codex / gpt-5-mini | builder, second-opinion; self-contained implementation and independent review | 3 | low, medium, high |
| gemini | gemini-2.5-pro / gemini-2.5-flash / gemini-2.5-flash-lite | builder, reviewer, second-opinion (via the Antigravity `agy` CLI) | 2 | medium |
| grok | grok-4.7 / grok-4.7 / grok-4-fast | builder, reviewer, second-opinion | 3 | medium |
| opencode | CLI default | builder | 2 | medium |
| copilot | CLI default | builder, security reviewer | 2 | medium |
| muse | muse-spark-1.2 on every tier | builder, second-opinion; Meta's Muse Code terminal agent | 2 | medium |
| cursor | IDE default | builder (handoff, no dispatch) | 0 | medium |
| antigravity | IDE default | builder (handoff, no dispatch) | 0 | medium |

## Delegation
Frontier-tier models are reserved for advice and sign-off: the lead (planning), the reviewers' final whole-diff review, and the verifier. Execution never uses a frontier model. Every builder takes the cheapest capable model and raises effort (low, medium, high, max) for harder work instead of escalating to a pricier model: mechanical is economy at low effort, normal is standard at medium, design is standard at high. Effort before escalation keeps token burn down without cutting the work. `scripts/delegate.py` resolves model and effort for a seat, `violates_execution_policy` flags a builder that ran frontier, and the receipt records a `Delegation policy` line that the final review blocks on.

The provider that fills the lead, advisory and sign-off seats is selectable with `/dts2-harness:model` (default Claude); the rule holds whichever provider leads. If the lead hits a usage or token limit or stalls, the harness writes the handoff and fails over to the next eligible provider (`scripts/failover.py`). `/dts2-harness:upgrade` is the one-command in-place upgrade (handoff, marketplace update, verify, re-run). `/dts2-harness:find-skills` is available any time to rescan the repo and suggest skills. Every detected agent gets a seeded project memory file (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) at scaffold.

## Settings
Copy `templates/dts2-harness.local.md` to `<repo>/.claude/dts2-harness.local.md`. Keys: `enabled`, `stop_checks`, `lessons_inject`, `lessons_max`, `auto_scale`, `max_builders`, `max_reviewers`, `use_worktrees`, `second_opinion`, `profile`, `max_execution_effort`, `delegation_strict`, `lead_provider`. Restart Claude Code after editing.

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

## Changelog

- 3.6.1 — gtm is self-sufficient: auto-installs marketing-skills, runs a deep-dive (optional deep-interview re-run), selects the applicable skills, and runs them as one seamless pass.
- 3.6.0 — strict delegation: frontier models only for advisory and sign-off, builders run the cheapest capable model at a complexity-scaled effort (new delegate.py); effort factored into the calc; Muse Code (Meta) added to the roster; plus /dts2-harness:upgrade (one-command in-place upgrade) and user-selectable lead provider via /dts2-harness:model; auto hand-off and lead failover on a usage/token-limit stall; every detected agent gets a seeded project memory file at scaffold; /dts2-harness:find-skills rescans and suggests skills on demand; request-refactor-plan finalization pass before tests; auto diagnose at the hard 3-round fix cap; loop-me check-in on run trigger; setup-pre-commit before every commit; code-review on first contact with a new repo; /dts2-harness:check-in shows complete vs outstanding against the end state; exhausted-budget effort is clamped to the profile's levels.
- 3.5.0 — new muse profile; per-role commands via `roster.py command` (grok review in plan mode, grok builders edit without a shell); gemini runs headless agy in plan mode on gemini-3.8 models, in the run skill and the SDK second opinion; codex drops the gpt-5-codex pin and reads stdin from /dev/null, and the lead commits for it; `roster.py classify` treats 402/429 as unavailable for the run and sends copilot's security seat to grok on the context-budget error; verifier HEAD guard; Supabase CLI route for database builders; Vercel verified-commit cancels are a note; handoff picks the newest stamped run. Hardening from review: grok seats deny Bash/MCP/subagents (reviewers also Edit/Write) and run with GROK_WORKFLOWS=0; grok builders edit only inside the working directory and never under .git, .grok, .claude or .cursor; prompts travel as files and `roster.py command` returns a quoted shell line; muse builds and gives second opinions but never takes a review seat (its second opinion runs with write, shell and web tools off); `classify` now requires `--exit-code`, reads only error lines from the tail of a failed run, and treats muse's recorded 402/429 forms as decisive at any exit.
- 3.4.0 — companion skills from mattpocock/skills wired into setup (grill-me, improve-codebase-architecture, writing-for-agents) and run (pr, resolving-merge-conflicts), installed per project when first needed and kept via keep.yaml, ask-matt → research for user questions, and diagnosing-bugs before the second fix round.
- 3.3.1 — gemini (Antigravity agy) and grok profiles now allow builder and reviewer roles besides second-opinion, per owner ruling D23.
- 3.3.0 — end-to-end Sections map in the interview; continuous dispatch: builders stay busy on ready sections, stalled ones are parked with action items.
- 3.2.0 — scope check with auto-pivot to the workspace root; context guard hook that stops a run and re-runs setup on a context spike or when started inside a member repo; project keep list (.harness/keep.yaml) so re-running setup never drops chosen plugins, skills (incl. npx skills add installs) or agents.
- 3.1.0 — Rules 9 (orchestration) and 10 (branches, worktrees, PRs) in discipline.md; worktree per builder by default in git repos; `run review-pr <n>`.
- 3.0.2 — Gemini is reached through the Antigravity `agy` CLI; roster finds agent CLIs that are off PATH via per-profile `searchPaths` and a `DTS2_BIN_<NAME>` override.

- 3.0.1 — learn skill description no longer contains angle brackets (claude.ai plugin upload rejected it).
- 3.0.0: end-state interview, Plan and Ship checkpoints, agent roster, harness discipline, deployment verification, action items, GTM, machine-prep tiers. See the root README.
- 2.1.0: machine-prep handles claude.ai synced plugins, org-required plugins, and project-level overrides.
- 2.0.0: first release.
