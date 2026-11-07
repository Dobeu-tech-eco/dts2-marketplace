# Changelog

Command reference for agents: `docs/COMMANDS.md`.

All notable changes to dts2-harness are recorded here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
Released versions live in this file. Work that has not been released yet lives in `changelog.d/` fragments (one file per batch) and in the `## Unreleased` section of the plugin `README.md`, until the release step joins it here.
Each version heading is followed by its release date on the first line (`_Released YYYY-MM-DD_`). The repository holds no release tags, so each date is the date of the commit that bumped the version.
The plugin was renamed twice: `dts2-harness` became `dts2` in 4.0.0 and `dts2` became `dt` in 5.0.0. Older entries keep the command names that were current at the time.

## [6.0.0]

_Released 2026-11-07_

Directory edition for the Claude plugin directory. Skills, roles, and documents only. Hooks and scripts stay in the GitHub marketplace install (`plugins/dts2-runtime`), because an unverified organization cannot publish them.

## [5.1.1]

_Released 2026-11-07_

Patch release: the plugin passes the Claude plugin directory's static checks, ships under the Dobeu Source-Available License 1.0, gets public READMEs and listing metadata, and picks up Composio and lanes fixes. Nothing breaking.

### Added

- Docs: rewrote the root and plugin READMEs for people (what it is, the problem it solves, requirements, install, wiring, day-to-day commands, update, uninstall, troubleshooting), added "More from Dobeu Tech Solutions" and Support sections, an "All commands" table covering all 27 slash commands, and fixed stale counts (27 skills, 8 agents) in `docs/COMMANDS.md`, `docs/GUIDE.md` and the onboard description.
- Listing: `plugin.json` and `marketplace.json` carry the publisher (Dobeu Tech Solutions, https://dobeu.net), homepage, a human description and a display name. Added `.claude-plugin/icon.png` and `.github/FUNDING.yml` (comments only until a handle is set).
- Repository: `.github/CODEOWNERS` requests a review from `@dobeutech` on every PR without making it required. `main` is protected: a PR is required, `test (3.12)` and `lint` must pass, force-push and deletion are blocked, and workflow runs from outside contributors need approval.
- `COMMAND-GUIDE.md` at the plugin root: the one-page list of every command, with install, update and requirements (python3 is needed for the safety hooks).
- `composio-setup.py` finds a `composio` CLI installed inside WSL when run on Windows without one on PATH. `DTS2_COMPOSIO_WSL=0` turns the lookup off. `composio-setup.py status` checks for the login directory inside WSL (existence only) when the CLI is only installed there.

### Changed

- License: the plugin and marketplace ship under the Dobeu Source-Available License 1.0 instead of MIT (`LICENSE` at the repo root and in the plugin folder; `plugin.json` license is `SEE LICENSE IN LICENSE`). You can still use, change and share it free. Selling it or relicensing it needs permission. Copies released under MIT stay MIT.
- `composio-setup.py decide --account yes` now saves `always_use: true` by default (#96). `--no-always-use` opts out, and `--account no` stays off. The composio skill and `docs/INVENTORY.md` say so.

### Fixed

- Hook scripts are statically readable by the plugin directory validator: every script path is spelled `${CLAUDE_PLUGIN_ROOT}/...`, `lib-settings.sh` reads settings in pure bash, inline `python3 -c` and `awk` programs moved to `scripts/hook_util.py`, and the PR-receipt logic moved to `scripts/pr_receipt.py` behind a thin wrapper.
- `composio-setup.py map` no longer reports zero connected toolkits when `composio connections list` prints an object keyed by toolkit slug. Toolkits with at least one active account are kept.
- `composio-setup.py map` falls back to `composio connections list` (active accounts only) when `composio dev connected-accounts list` fails, and records `connected_source` in its output and the tool map.
- Stop hook works on stock macOS: when GNU `timeout` is missing it uses Homebrew's `gtimeout`, or runs the step with the hook's own timeout as the backstop. Before, every step failed with "command not found", the handoff note was never written, and each Stop re-ran the checks as red. `xargs -r` (GNU only) dropped from the change fingerprint.
- Lanes: when an old son's process group ignores SIGINT and gets SIGKILL, re-dispatch waits (up to 5 seconds) until the group is gone, so a lane is never restarted while the old processes are still exiting.

## [5.1.0]

_Released 2026-11-06_

Minor release: agent profiles with custom names (`claude-api`, `codex-api`, `grok-api`), per-agent rules enforced at dispatch, launch and tool time, a spend ledger, env isolation, an unattended mode and speed defaults. Nothing breaking.

### Added

- `/dt:pr-sweep [owner/repo] [--stale-days N] [--mine|--author A|--head-prefix P] [--optimise-ci]` clears open and stale PRs in one pass with parallel workers. It sorts every PR into a bucket (green, needs rebase, CI red, stacked, superseded, stale, draft, needs you). `scripts/pr_sweep.py` does the inventory over REST-only `gh api` and prints JSON.
- Autopilot open-PR cap: `open_pr_cap` (default 5, under `autopilot:` in `.harness/config.yaml`). A run with that many of its own PRs open runs `/dt:pr-sweep --run <stamp>` before it branches a new step.
- User and project agent profiles: `~/.dts2/agents/*.json` (override with `DTS2_USER_AGENTS_DIR`) and `.harness/agents/*.json` layer over the bundled ones, field by field, and `extends: <name>` deep-merges a parent. `roster.py list`, `add` and `rename` manage them, and `/dt:model` gains an "Add or rename an agent" flow.
- API-key profiles `claude-api`, `codex-api` and `grok-api`. `scripts/api_keys.py` resolves a profile's key (`env:`, `keyring:`, `op://`, `doppler:`) and hands it only to that agent's child process. Docs: the "API agents" section of `docs/GUIDE.md` and `docs/API-AGENTS.md`.
- Per-agent rules: a roster entry may carry a `rules:` block (`allow_tasks`, `deny_tasks`, `max_tier`, `paths_deny`, `no_secrets`, `read_only`, `max_cost_usd_per_run`, `max_cost_usd_per_day`) checked by `scripts/agent_rules.py`. Dispatch skips an agent whose rules deny the task and fails over to the next eligible one. `roster.py rules <name> --show | --set key=value | --reset` edits the block.
- Spend ledger: `.harness/spend.jsonl` records each named agent's run cost. `roster.py probe` marks an agent exhausted for the day once it reaches its daily cap, and `roster.py exec` refuses to launch a spent or over-tier agent.
- Unattended mode: `autonomy: unattended` in `.harness/config.yaml` lifts the `max_fullauto_loops` cap. `scripts/loop_guard.py` stops the `/dt:fullauto` outer loop on a `.harness/STOP` file, a `dts2:stop` PR label or a spent budget. `templates/settings.unattended.json` and `scripts/unattended.py` give a locked-down permission profile, and a denied tool becomes a `need-human` item instead of a stalled prompt.
- Merge directly when green: a human-only `merge_policy` approval (`"merge_policy": ["auto-when-green"]` under `dts2_approvals` in `.claude/settings.local.json`) lets autopilot run `gh pr merge <n> --squash --match-head-commit <sha>` after `merge-go-step` and green CI. Without the grant, a plain `gh pr merge` stays blocked.

### Changed

- Speed: verifier and fixer agents run on Sonnet. Fix rounds 1 to 3 stay on Sonnet and rounds 4 and 5 go to a fresh Opus worker. `son_model` defaults to `sonnet` (set `son_model: opus` for hard tasks), and a resumed son keeps the model its lane started on.
- Speed: builder, verifier, reviewer, fixer, scout and auditor agents ask for a one-hour prompt cache. CI gets a pip cache, a Python 3.12-only matrix on pull requests (full matrix on main and the merge queue) and parallel tests with pytest-xdist.
- Env isolation: one scrubbed child-environment builder (`son_launch.scrub_env`) serves every son, council seat, second opinion and `roster.py command`. A subscription agent never receives `*_API_KEY` variables, so a stray key cannot switch it to API billing. An `api-key` agent receives only its own key. Codex now reads `the Codex API key`.

### Fixed

- The SDK second opinion no longer pulls an API key into the subscription `codex` or `grok` CLI. A provider key is injected only when the backend is an explicit `codex-api` or `grok-api`.
- A roster entry that points at a profile (`name: scout, profile: grok`) runs under its own name, so its rules, auth, `DTS2_AGENT` and spend ledger use `scout`. The policy gate follows that pointer too.
- `roster.py exec` reads project profiles and the roster from `--workspace`, and `roster.py command` no longer prints a real API key (credential variables read `<redacted>`).
- `paths_deny` matches relative paths after `..` and `./` are resolved, so `src/../infra/main.tf` is denied by `infra/**`.

### Security

- `no_secrets` is on by default for a non-subscription agent. An API-key profile (`keyRequired`) always runs as `api-key` with restricted defaults, even when its roster entry says `auth: subscription`.
- An untrusted project profile cannot set executable or credential fields (`readOnlyCommand`, `budgetFlag`, `apiKeyRef`, `defaultModel`, `keyRequired`, `leadEligible`, `auth` and others). They are dropped with a warning unless the project is trusted.
- `tests/test_secret_scan.py` fails when a key-shaped string ships in templates, profiles, skills, agents or docs.

## [5.0.0]

_Released 2026-11-06_

Plugin renamed from `dts2` to `dt` so every command reads `/dt:<command>`.

### Changed

- Breaking: plugin renamed `dts2` -> `dt` (version 5.0.0); commands are now `/dt:<command>` and agents `dt:<agent>`. The marketplace keeps the name `dts2` (install with `/plugin install dt@dts2`), and the plugin folder, the settings file `.claude/dts2-harness.local.md`, the `.harness/` and `~/.dts2/` paths, the `DTS2_*` variables and the `<!-- dts2:start -->` / `<!-- dts2:end -->` markers keep their names.
- Migration: existing installs run `/plugin uninstall dts2@dts2` (`dts2-harness@dts2` on a version before 4.0), `/plugin marketplace update dts2`, `/plugin install dt@dts2`, `/reload-plugins`; settings and `.harness/` state need no change.
- A keep list, profile or composio overlap check that still names the old ids (`dts2@dts2`, `dts2-harness@dts2`) is handled: the pre-check no longer tries to update them as an extra plugin, machine-prep no longer protects them from being disabled, and composio-setup still never offers to disable the harness under any of its names.

## [4.1.0]

_Released 2026-11-06_

Minor release: personal knowledge store, repo review, Composio, agent incidents, fleet view, cooldowns, prompt intake and hooks setup. Nothing breaking; the 4.0.0 migration steps are unchanged.

### Added

- `/dts2:knowledge` (user only): a private, git-synced store of standing preferences, glossary terms and cross-project learnings, with an optional Cloudflare backend (`scripts/knowledge.py`, `scripts/knowledge_cloudflare.py`); `/dts2:setup` reads it and asks before applying a preference.
- `/dts2:ask-expert` reviews one repo before setup (goal questions, clarity gate, evidence report, optional panel with `panel-tally`) and `/dts2:repo-sweep` runs the quick pass over an owner's repos with one cleanup screen (`scripts/ask_expert.py`, `council.py --allow-research`).
- `/dts2:composio` (user only) connects a Composio account, maps toolkits and connected accounts, and offers to disable overlapping tools without deleting anything (`scripts/composio-setup.py`); `onboard`, `machine-prep`, `improve-scan.py` and `find-skills` take covered tools into account.
- `/dts2:incidents` (`list`, `live`, `brief`, `review`, `resolve`, `promote`, `lessons`) with a read-only `incident-reviewer` agent and an agent telemetry hook that records thin briefs, empty or partial reports, rework and hung spawns; `incident_capture: false` turns capture off. Skill count is now 26 and agent count 8.
- `/dts2:fleet` lists every harness session on the machine and shows a session's handoff, tasks, intake, lanes and cooldowns read-only; `/dts2:check-in all` gathers check-in items from all sessions into one report (`hooks/fleet-session.sh`, `scripts/fleet.py`).
- `/dts2:cooldown` and `scripts/cooldowns.py` track agents paused after a usage limit with their reset dates; `roster.py` and `failover.py` skip cooling agents and `hooks/session-cooldowns.sh` reports them at session start.
- Prompt intake: a `UserPromptSubmit` hook (`hooks/prompt-intake.sh`, `scripts/intake.py`) queues every prompt typed while the harness works as fold, clarify or steer, and `/dts2:steer` is the only command that stops running work to re-plan.
- Onboarding hooks setup (`scripts/hooks-setup.py`, `templates/hooks/`) merges picked hooks into project, local or user settings with a backup, including database guard hooks; `find-skills` now audits every improvement option through the read-only `scripts/improve-scan.py`.

### Fixed

- Bot-review fixes: fleet broadcast delivery keeps a per-session `.seen.json` marker so no message is skipped; incident lessons keep distinct `K-` ids, project-prefixed promoted keys and the full injected id forms; intake updates run under the file lock and the hook never waits on it; `agent-memory.py` migrates the pre-4.0 managed block in place; `ask_expert.py` backup, delete and panel voting corrected; the hook speed test no longer fails on one slow CI sample.

## [4.0.0]

_Released 2026-11-05_

Plugin renamed from `dts2-harness` to `dts2` so every command reads `/dts2:<command>`.

### Changed

- Breaking: plugin renamed `dts2-harness` -> `dts2` (version 4.0.0). Commands are now `/dts2:<command>` and agents `dts2:<agent>`. The plugin folder, the settings file `.claude/dts2-harness.local.md` and the `.harness/` state paths keep their names.
- Migration: existing installs run `/plugin uninstall dts2-harness@dts2`, `/plugin marketplace update dts2`, `/plugin install dts2@dts2`, `/reload-plugins`. Settings and `.harness/` state need no change.
- Docs: duplicated changelog fragments were removed and the GUIDE title follows the new name.

## [3.11.1]

_Released 2026-11-05_

Patch release: a sandbox fix so sons can run the plugin's own scripts, a guard fix, and three lessons from real runs.

### Fixed

- Son sandbox (D74): the son guard no longer treats an interpreter's script argument inside the plugin's own `scripts/` as a write target, so `lanes.py` runs in a son. `lane_env` sets `CLAUDE_PLUGIN_ROOT` and keeps pnpm's store. The lessons from the incident are recorded.
- `guard.mask_literals` opens a substitution context only for an unescaped `$(`, so an escaped `\$(` or `$$(` no longer hides a following `$(printenv)`. `git commit -m '$(env)'` is unchanged (R3).
- Context guard (H-004): an approved plan the run never saved as `plan.md` counts as the plan checkpoint.
- Builders (H-006): they no longer run `the publisher's installer for` inside their own checkout. They run `/improve-codebase-architecture` only when it is installed.

### Added

- Handoff (H-003): a pending plan or ship checkpoint is now the next action when a run resumes.

## [3.11.0]

_Released 2026-11-05_

Round 2 hardening: a policy gate for the head, son containment and lifecycle, the mailbox, merge and fold recovery, signed receipts, an eval A/B runner, report ops and agent completion gates. The optional cross-model review step was skipped for this release by decision of the owner.

### Added

- Policy gate (`scripts/policy_gate.py`, `templates/policy.json`, `hooks/policy-gate.sh`): a PreToolUse check for the head and sons that denies force-push in all its spellings, `--admin`, deploy CLIs and environment dumps.
- Son containment: sons commit a branch and the head publishes (`scripts/head_publish.py`). Protected paths (`scripts/protected.py`), a human-only approval channel (`scripts/approvals.py`), an explicit tool allowlist with `permissions.deny`, a provider env allowlist and ballot provenance (`scripts/ballot_dispatch.py`) limit what a son can touch.
- Son lifecycle: each son starts in its own session and writes `son.json` and `exit.json`. `lanes.py reconcile` maps exits to lane states, `lanes.py gc` closes expired leases, `lanes.py wait` blocks on phase changes instead of polling, and `son_stream.detect_stuck` marks a looping lane stalled.
- Mailbox (`lanes.py mailbox`): versioned question, answer and need-human messages, send-backs with epochs, and a `merge-go.json` grant a son refuses when its head moved. `lanes.py override` logs a human override.
- Merge and fold recovery: `lanes.py fix-attempt` caps post-merge fixes and then opens one revert PR. `fold --apply` and `fold-close` record and close superseded PRs. Integration-lane routing is written to `routing.json`.
- Signed receipts: `scripts/receipts_sign.py` adds a hash-chained journal and HMAC signing with a key file the son environment never receives. `scripts/plugin_options.py` reads `CLAUDE_PLUGIN_OPTION_<KEY>`.
- Eval runner A/B mode (`--arm-b-env`, `--runs`) reports median, range and a faster, slower or inconclusive verdict. `lanes.py report` adds run-wide sections and a per-son line.
- Agent completion gates: `hooks/subagent-stop.sh` blocks a verifier stop while the newest run ledger lacks a check line. The verifier gets `Read, Grep, Glob, Bash` and the reviewer loses Bash. A failed ballot dispatch (error, malformed ballot, 429, timeout) retries in the same round.
- Hooks: every hook runs `python3 -I`, `hooks/lib-settings.sh` parses settings the way `lanes.read_setting` does, and the stop hook shares one deadline and can block once on a red check (`stop_checks_block: true`).
- Docs: `docs/GUIDE.md` (the agent guide for the 3.10 line), `docs/COMMANDS.md`, and refreshed `docs/INVENTORY.md` and `ARCHITECTURE.md`.

### Changed

- `skills-check.py` no longer upgrades the plugin while a lane lease is live, and the `skills` npm CLI is pinned to a version. The marketplace repo name comes from `DTS2_MARKETPLACE_REPO`, `plugin.json` or `git remote` instead of a hard-coded org.
- Evolve climbs a hardening ladder (hook, then test, then check, then prose), and the PR template carries a "Decisions and declined findings" section.

### Fixed

- Policy gate and merge guard: bundled `env` flags no longer hide the command word, a flag-only deny rule fails closed on a shell expansion, single-quoted `$(...)` is text, and a sub-command matches only at its own position (so `gh pr create --title secret` is not denied as `gh secret`).
- Dedupe ids are recorded only after the write succeeds, so a failed first attempt never turns a retry into a silent duplicate. `council.py next-round` seeds its instance counter from earlier allocations.
- Verifier stop check reads the current run's ledger only. `merge-go-step` applies the same base-health and merge-mutex refusal as `merge-go`. `receipts_sign.py` fails closed when its key file is set but unreadable.
- Head push probe runs without the repo's hooks, and `lanes.py publish` is head-only.
- Review rounds closed a long list of smaller findings: stale-epoch heartbeats, revert-branch retries, paginated check runs, `#7` matching `#70`, renamed protected files, and `A && B || C` patterns in hook scripts.

### Security

- Sons are denied `git push`, `gh pr` and `gh api`. Unattended merges need required checks plus a review or merge queue, and a production-deploying merge needs a human approval.
- SessionStart lessons, state and action items are printed inside an untrusted-content fence, capped at 4000 characters.

## [3.10.0]

_Released 2026-11-05_

Parallel autopilot hardening: lane lifecycle, son containment, merge ordering, council seats, supply chain and a docs inventory.

### Added

- Lane lifecycle in `scripts/lanes.py`: `transition` is the only writer of a lane's phase, with `heartbeat`, `budget`, `merge-order` and `merge-go`. A per-run merge journal lets `merge-resume` settle a merge a dead head left half done. Leases carry `expires_at`, a TTL and the session id.
- Planning: lanes may declare `provides`, `consumes` and `stubbed_on`, and `plan_graph.py merge-order` puts providers first. Owners may be `dir/` prefixes or globs.
- Son containment: sons launch without `--bare`, with `--permission-mode dontAsk`, a tool allowlist, default-deny network egress and an empty MCP config. `lanes.py spawn` passes turn, fallback-model and budget caps from a new `budget:` config block.
- Merge guard: `hooks/merge-guard.sh` and `scripts/guard.py` gate `gh pr merge`, merge paths in `gh api` and pushes to protected branches unless a `merge-go.md` names the head and base.
- Council: `scripts/seat_swap.py` swaps in the next provider when a seat times out, and `council.py blind` strips author names from ballots.
- Checks gate (`scripts/checks.py`): tests, typecheck, lint, a secret scan and a scope check run before any vote and are recorded in the run ledger. `scripts/builder-audit.py` and `scripts/plan-gate.py` audit builders and plans, and plans need a `## Foundation` section.
- Shared modules: `state_io.py` (stores, `"v": 1` records, atomic writes, migration) and `proc.py` (process runner with a fake for tests).
- Memory: lessons take `{paths: ...}` globs, track promotion and regressions, and prune after 90 days. PreCompact refreshes the handoff.
- Production readiness: `scripts/prod-scaffold.py` writes CI, `RUNBOOK.md` and `ops/` notes, `scripts/app-type-detect.py` names the app type, and `scripts/bump-version.py` joins the release step.
- `docs/INVENTORY.md` lists every skill, agent, hook, script and Makefile target, with a test that keeps it complete.

### Changed

- `skills/run`, `skills/autopilot` and `skills/setup` are short router files plus phase files read on demand. Text moved, content kept.
- `lanes.py` is a thin CLI over the `scripts/lanes/` package. Branch names no longer nest (`dts2/<stamp>/main`, `lane-<x>`, `step-<step>`), and `lanes.py branch-check` needs git 2.38 or newer.
- Skill and agent descriptions are cut to about 250 characters, and `scripts/context-tax.py` exits 1 above 6000 tokens. Mechanical sections dispatch the builder on `haiku` at low effort.

### Fixed

- `lanes.py lease` and `plan` fail closed when `gh` is missing. Merge order honors `merge_after`, and `reconcile` never resumes a lane under a running son.
- Lock handling in `state_io` can no longer free a successor's lock. `roster.classify_dispatch` treats exit 143 as a timeout so the council can swap the seat.
- `builder-audit` sees both paths of a rename. The onboard skill counted six agents; there are seven.

### Security

- Sons run without `a GitHub token` or the SSH agent socket and cloud credentials unless `DTS2_SON_ENV_PASS` names them.
- Companion skills can be pinned to a commit with `pin: <40-char sha>` in `.harness/keep.yaml`. `a bulk skill update` no longer runs unattended, and `skills-check.py` writes update proposals that apply only after an explicit yes.
- Check logs and action items are redacted of key-shaped strings, bearer tokens and URL passwords.

## [3.9.1]

_Released 2026-11-04_

### Added

- End-to-end test for dpp: two blocked lanes folded onto one PR, items marked done, and resume finds the PR.

### Fixed

- `task-ledger.py` writes one row per PR, so a PR folded from several lanes resolves only when every lane's items are done.

## [3.9.0]

_Released 2026-11-04_

Parallel autopilot: one head plans lanes and one headless autopilot son works each lane.

### Added

- New `/dts2-harness:dpp`, `/dts2-harness:dpp-full` and `/dts2-harness:fullauto`. The head plans lanes from the check-in list (`lanes.py plan`, with a feasibility `check`, `estimated_spend` per lane and a `--full` scan that never pads and reports `no further parallel work found`), gets approval, and starts one son per lane.
- Supervision: `lanes.py status` marks a lane stalled past `builder_timeout_min`, `sendback` refuses a third send-back, `release` frees a lease, and questions the head can answer never reach you.
- Merges are serialized with `merge-go.md`. Blocked lanes fold into the fewest PRs (`lanes.py fold`). Lessons and action items fold back to the head.
- Reporting: `dpp-report.md` is checked by `lanes.py report-check` (every lane section plus `## Spend` and `## Task ledger`), and `task-ledger.py` runs last. `resume` merges PRs whose `TASK_` items are done first.
- `fullauto` loops check-in between rounds and stops through `lanes.py stop-check` when nothing is outstanding and every lane is done or blocked.
- Lane foundations: locks, ID reservation, lane leases, and son mode for autopilot (bundles, post-merge check, adjudication, task ledger).

## [3.8.1]

_Released 2026-11-04_

### Changed

- The council sits only after three failed rounds of the normal vote. `council.py eligible` reads the step's vote history and allows the council only when three complete rounds on the same ballot (plan or build) have all failed. Anything less returns `eligible: false` with what to do instead. `council.py dossier` refuses to build early.
- A failed or invalid Fable tiebreak no longer jumps to the council. It counts as a failed round and gets a fix round. Each ballot gets its own three rounds before escalation.

## [3.8.0]

_Released 2026-11-04_

### Added

- Autopilot council. When three rounds of voting do not settle a step, autopilot convenes five frontier seats spread across as many usable providers as it can (claude, codex, gemini, grok, cursor, muse). `council.py seats` picks them, and a `council:` block in `.harness/config.yaml` sets order, exclusions and extra models. A provider takes a second seat only with a different model.
- Each seat reads a dossier of the step's full history and votes. Every seat that votes against the majority writes a dissent brief. Claude Fable 5.1 as head of council then decides: run more fixes, strike items (each becomes a Decisions action item), or approve.
- `scripts/council.py` builds the dossier, tallies ballots, and rejects a decision record that skips a dissent or the history. `council.py ledger` writes the whole council to `.harness/council.md`, `.harness/state.md` and `.harness/lessons.md`.
- `roster.py command` gains `--model` so a doubled seat runs its exact model. The head of council's brief goes in the PR, the receipt, check-in and the final report.

### Security

- The council is bounded: one council per step, at most two head-of-council fix rounds, then park. A council never overrides a hard stop or branch protection.

## [3.7.2]

_Released 2026-11-04_

### Fixed

- The pre-check never deletes or overwrites a git-tracked file. `a bulk skill update` had deleted committed skill files (vendored Stripe skills under `.claude/skills/`). Every mutating `the publisher's skill installer` call now runs under a snapshot that puts tracked skill files and a tracked `skills-lock.json` back byte-for-byte, uncommitted edits included.
- A retired or swapped-out skill with tracked files is skipped, not removed. When the repo is under git but `git ls-files` fails, the update is skipped. Skips are reported in `skills.tracked_skipped` and `skills.tracked_check`.

## [3.7.1]

_Released 2026-11-04_

### Changed

- The pre-check splits into a once-a-day freshness sweep (marketplace refresh, `a bulk skill update`, gone-upstream checks, harness-version check, gated by `.harness/.skills-checked`) and a per-run fast path that only checks skills are present, installs any missing, and acts on a detected upgrade. This cuts per-run pre-check time by about 90%. `--force-full` forces the sweep.
- `.harness/.skills-checked` and `.harness/upgrade-from.txt` are gitignored.

## [3.7.0]

_Released 2026-11-04_

### Added

- Pre-check before every run command (`scripts/skills-check.py`): installs every companion and `keep.yaml` skill with `-a claude-code --copy -y` (a bare install's symlink silently failed on Windows), removes retired skills, swaps a skill gone upstream for the highest-install live alternative, and refreshes plugin marketplaces. When a newer harness is published, it saves the spot and upgrades in place.
- New `/dts2-harness:ship`: a user-started PR with pre-checks, a receipt, a richer PR template, and a PR and branch sweep down to main and dev.
- New `/dts2-harness:feature`: roadmap a feature with a scoped deep interview and sync every plan doc.
- New `/dts2-harness:autopilot`: no human checkpoints. Three frontier providers must agree on plan and build, Claude Fable 5.1 breaks a split, and each step becomes one PR merged on green CI.
- Evolve runs automatically after every ship on open harness lessons.

### Changed

- `resolving-merge-conflicts` (removed upstream) is replaced by `warpdotdev/common-skills@resolve-merge-conflicts`.

### Removed

- `/dts2-harness:upgrade`, because the pre-check now finishes upgrades on the next run.

## [3.6.3]

_Released 2026-11-03_

### Changed

- Codex tiers are pinned from a ChatGPT Pro model list: frontier `gpt-6-astra`, standard `gpt-6.1-sol`, economy `gpt-6-luna`. An unpinned run (default `gpt-6.1-sol`) reports as the standard tier.
- `codex exec` gets `-m` and `-c model_reasoning_effort`, so a global `config.toml` setting of high does not apply to every seat. Builders stay on standard or economy at low to high effort. Sign-off may use xhigh. Max and ultra run only when explicitly requested.

## [3.6.2]

_Released 2026-10-27_

### Changed

- The builder finalization pass uses `improve-codebase-architecture` scoped to the builder's file set, because upstream retired `request-refactor-plan`. A manual scoped simplification pass is the documented fallback.
- The hard-cap `diagnose` companion, renamed upstream to `diagnosing-bugs`, becomes a fresh `diagnosing-bugs` pass.

## [3.6.1]

_Released 2026-10-22_

### Changed

- The gtm skill is self-sufficient: it auto-installs marketing-skills, runs a deep-dive (with an optional deep-interview re-run), selects the applicable skills, and runs them as one pass.

## [3.6.0]

_Released 2026-10-22_

### Added

- Strict delegation: frontier models only for advisory and sign-off. Builders run the cheapest capable model at an effort scaled to complexity (new `delegate.py`), and effort is part of the cost calculation.
- Muse Code (Meta) joins the roster.
- `/dts2-harness:upgrade`, a one-command in-place upgrade, and a user-selectable lead provider through `/dts2-harness:model`.
- Auto hand-off and lead failover when the lead stalls on a usage or token limit.
- Every detected agent gets a seeded project memory file at scaffold.
- `/dts2-harness:find-skills` rescans and suggests skills on demand. `/dts2-harness:check-in` shows complete versus outstanding work against the end state.
- Run-flow additions: a `request-refactor-plan` finalization pass before tests, auto `diagnose` at the hard three-round fix cap, a `loop-me` check-in on run trigger, `setup-pre-commit` before every commit, and a code review on first contact with a new repo.

### Fixed

- Exhausted-budget effort is clamped to the profile's levels.

## [3.5.0]

_Released 2026-10-22_

### Added

- New `muse` agent profile.
- Per-role commands through `roster.py command`: grok review runs in plan mode and grok builders edit without a shell.
- Gemini runs headless `agy` in plan mode on gemini-3.8 models, in the run skill and in the SDK second opinion.
- `roster.py classify` treats 402 and 429 as unavailable for the run, and sends copilot's security seat to grok on the context-budget error.
- Verifier HEAD guard: it records the start and end SHA and attributes checks per commit.
- Supabase CLI route for database builders.

### Changed

- Codex drops the `gpt-5-codex` pin and reads stdin from `/dev/null`, and the lead commits for it. Codex builders pass `--sandbox workspace-write`.
- Copilot seats run headless with `-p`, and its spent-quota error drops it for the run. An unrecognised non-zero dispatch exit fails the seat.
- Prompts travel as files, and `roster.py command` returns a quoted shell line.

### Fixed

- `latest_run` prefers stamped run folders over named ones.
- Grok seats deny edits, subagents and MCP explicitly, and run with `GROK_WORKFLOWS=0`. Grok builder edits stay in the working directory.
- The SDK's agy print timeout fires before the 600-second limit and becomes a note.

## [3.4.0]

_Released 2026-10-22_

### Added

- Companion skills from mattpocock/skills wired into setup (`grill-me`, `improve-codebase-architecture`, `writing-for-agents`) and run (`pr`, `resolving-merge-conflicts`). They install per project when first needed and are kept through `keep.yaml`.
- `diagnosing-bugs` runs before the second fix round, and `ask-matt` becomes `research` for user questions.

## [3.3.1]

_Released 2026-10-22_

### Changed

- The gemini (Antigravity `agy`) and grok profiles allow builder and reviewer roles as well as second opinion, per owner ruling D23.

## [3.3.0]

_Released 2026-10-21_

### Added

- End-to-end Sections map in the interview.
- Continuous dispatch: builders stay busy on ready sections, and stalled ones are parked with action items.

## [3.2.0]

_Released 2026-10-21_

### Added

- Scope check with an automatic pivot to the workspace root.
- Context guard hook that stops a run and re-runs setup on a context spike or when started inside a member repo.
- Project keep list (`.harness/keep.yaml`), so re-running setup never drops chosen plugins, skills (including `the publisher's installer for` installs) or agents. The workspace scaffold writes it, and machine-prep treats its plugins as required.

## [3.1.0]

_Released 2026-10-21_

### Added

- Rule 9 (orchestration) and Rule 10 (branches, worktrees, PRs) in `discipline.md`.
- `run review-pr <n>`.

### Changed

- Builders get a worktree by default in git repos.

## [3.0.2]

_Released 2026-10-21_

### Changed

- Gemini is reached through the Antigravity `agy` CLI.
- The roster finds agent CLIs that are off PATH, through per-profile `searchPaths` and a `DTS2_BIN_<NAME>` override.

## [3.0.1]

_Released 2026-10-21_

### Fixed

- The learn skill description no longer contains angle brackets, which the claude.ai plugin upload rejected.

## [3.0.0]

_Released 2026-10-21_

Version 3 turns the harness into an interview-driven pipeline with explicit checkpoints.

### Added

- End-state interview in setup: repos, harnesses, topology and skills rounds, a scaffold-only mode, and batch mode that never asks.
- Plan and Ship checkpoints in run, with a change receipt, an end-state file, a state file and a PR template. Hooks add the receipt and template on `gh pr create` and `gh pr edit`.
- Agent roster: seven agent profiles, availability and budget probes, cost tiers, subscription login first with API-key agents by opt-in, and a grok profile.
- Harness discipline (`discipline.md`) and run flow additions: a code finish pass, a stack blueprint, and `/dts2-harness:action-items` with a pass-off file.
- Deployment verification: a production walkthrough, a troubleshoot round for failed deploys, and building a production target when none exists.
- Learning loop: `learn` auto mode with promotion, run metrics and harness lessons, plus new `gtm`, `evolve` and `onboard` updates.
- Machine-prep tiers (light, standard, strict) with usage counts and redundant pack detection, and new scripts `ensure-ignored`, `clarity-score` and `usage-scan`.
- SDK runner: ship checkpoint, receipt and roster support, and `--ship` and `--live-only` flags in `dts2-run.py`.

### Changed

- The end-state slicing, done section and critique, security and walkthrough review axes now steer the lead, builder and reviewer agents.

## [2.2.0]

_Released 2026-10-17_

### Changed

- machine-prep reports plugin-supplied agents per source (`claudePluginAgents`) beside the blueprint's user-agent count, counts nested agent files, and reports claude.ai skill sync.

### Fixed

- machine-prep finds synced plugins that ship without a manifest, which keep-list mode used to miss.

## [2.1.0]

_Released 2026-10-17_

### Added

- machine-prep counts plugins synced from the claude.ai account toward the budget, turns syncing off (or disables all but a keep list), skips org-required plugins, and flags repos whose settings re-enable plugins you turned off.

## [2.0.0]

_Released 2026-10-17_

First release.

### Added

- Six agents: lead, builder, reviewer, verifier, scout and auditor.
- Six skills: onboard, machine-prep, setup, run, learn and sdk.
- machine-prep (`scripts/machine-prep.py`, driven by `profiles/blueprint.json`) scans a machine, plans and applies pruning. Pruning disables with a settings backup first.
- Batch and workspace modes in setup for many repos.
- Hooks: SessionStart loads recent lessons, and Stop runs typecheck and lint.
- `sdk/dts2-run.py`, a headless runner with an optional Codex or Gemini second opinion.
- `env-detect.py` for WSL and Linux, `repo-size.py` for team sizing (tiers S, M, L and XL), PowerShell and bash installers, and a settings template at `.claude/dts2-harness.local.md`.
