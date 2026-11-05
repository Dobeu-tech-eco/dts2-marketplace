# dts2-harness command inventory

Every command an agent or a user can run in this plugin, with its purpose, exact usage and what calls it. Built from the files themselves: `skills/*/SKILL.md` and the phase files beside them, `agents/*.md`, `hooks/hooks.json` and `hooks/*.sh`, the argparse definitions in `scripts/*.py` (and `scripts/lanes.py` for the lane commands), and the root `Makefile`. A test (`tests/test_inventory_complete.py`) fails when a `lanes.py` subcommand or a skill directory is missing from this page, so add a row in the same change that adds a command.

In examples, `$P` stands for `${CLAUDE_PLUGIN_ROOT}`, `<repo>` for a repo root, `<stamp>` for a run stamp and `<manifest>` for a lane manifest (`lanes.json`). Scripts print one JSON object on stdout unless noted. The "Since" column is `new` for a command added in 3.10.0 and `changed` for an existing command whose arguments or output changed; section 7 lists the changes.

For a shorter orientation (how to talk to the harness, which command when, the head, son and council flow) read `GUIDE.md` first.

Contents: 1 Skills, 2 Agents, 3 Hooks, 4 CLI scripts (4.1 state and progress, 4.2 detection and scaffolding, 4.3 roster, council and orchestration, 4.4 review and build gates, 4.5 parallel lanes, 4.6 maintenance, 4.7 hook entry points, 4.8 other entry points), 5 Library modules, 6 Makefile targets and CI, 7 Changed in 3.10.0.

## 1. Skills (slash commands)

Invoke as `/dts2-harness:<name>`. Skills with `disable-model-invocation: true` in their frontmatter (`dpp-full`, `fullauto`, `machine-prep`, `model`, `onboard`, `sdk`) run only when the user types them. "Runs" lists the scripts the skill's own files name; "Hands off to" lists the skills it names.

| Command | Purpose | Usage and arguments | Runs | Hands off to |
|---|---|---|---|---|
| `/dts2-harness:onboard` | Explain the harness (agents, skills, roster, tiers, lessons, headless runner) and recommend where to start. Explanation only; changes nothing. | no arguments | `delegate.py` (named in its text) | `autopilot`, `check-in`, `dpp`, `dpp-full`, `feature`, `find-skills`, `fullauto`, `model`, `ship` |
| `/dts2-harness:machine-prep` | Scan this computer's agent tooling, compare to the blueprint profile, prune by disabling, set up the slim startup. | no arguments; drives `machine-prep.py audit\|plan\|apply` | `env-detect.py`, `machine-prep.py` | none |
| `/dts2-harness:setup` | Interview to an approved end state (`.harness/end-state.md`), then scaffold harness config in one repo, many repos or a workspace. A short router plus `phase-1-interview-a.md`, `phase-1-interview-b.md`, `phase-2-scaffold.md`. | `[path ...] [--scaffold-only]`; several paths means batch (scaffold only) | `scope-check.py`, `repo-size.py`, `app-type-detect.py`, `deploy-detect.py`, `clarity-score.py`, `roster.py`, `ensure-ignored.py`, `agent-memory.py`, `prod-scaffold.py` | `run`, `evolve` |
| `/dts2-harness:run` | Plan, build, review and verify pipeline on a task in one repo or workspace; ends with a receipt. A short router plus `phase-0-size.md` to `phase-4-ship.md`, `modes.md` and `operations.md`. | `<task>`, `resume`, `section <#>`, `add secret NAME`, `review-pr <number>` | `scope-check.py`, `briefs.py`, `checks.py`, `council.py`, `delegate.py`, `roster.py`, `failover.py`, `plan-gate.py`, `plan_graph.py`, `builder-audit.py`, `flags_collect.py`, `findings.py`, `review_split.py`, `rollback_ref.py`, `walkthrough_fallback.py`, `companion-gate.py`, `skills-check.py`, `handoff-write.py`, `lanes.py` (`check`, `merge-plan`), `metrics.py`, `action-items.py`, `deploy-detect.py`, `ensure-ignored.py`, `agent-memory.py` | `setup`, `evolve`, `find-skills`, `action-items` |
| `/dts2-harness:learn` | Consolidate reviewer and verifier findings into `.harness/lessons.md`; prune stale lessons (only after the user approves the drops). | no arguments, or `promote <L-NNN>` | `lessons.py`, `metrics.py`, `scope-check.py`, `action-items.py` | none |
| `/dts2-harness:sdk` | Set up and run the pipeline headless with the Agent SDK (CI, cron, servers, WSL). | no arguments; runs `sdk/dts2-run.py` (section 4.8) | `sdk/dts2-run.py`, `roster.py` | none |
| `/dts2-harness:evolve` | Change the harness itself in its source repo: edit, validate, test, bump versions, commit; push only on an explicit yes. | no arguments, or `deploy` to change the repo's deploy target | `deploy-detect.py` | none |
| `/dts2-harness:action-items` | Show open Secrets, Decisions, Handoff, Deploy and Promotions items with age, owner and resolving command; mark done, add, assign. | no arguments (list), or the `done`, `add`, `assign` subcommands | `action-items.py`, `handoff-write.py` | `run`, `learn` |
| `/dts2-harness:gtm` | Go-to-market in one pass: installs `marketing-skills` if missing, runs a deep-dive and applicable skills, ends with a readiness scorecard. | no arguments | `marketing-select.py`, `ensure-ignored.py` | none |
| `/dts2-harness:ship` | Ship the current branch as a pull request: pre-check, repo checks, secret scan, verifier and reviewer, receipt, push, open PR; then sweep stale branches and PRs. Never merges. | `[base]`; base defaults to `dev` when it exists on the remote, else the default branch | `skills-check.py`, `handoff-write.py` | none |
| `/dts2-harness:feature` | Add a feature to the roadmap: clarity score, interview when unclear, lead writes it into the end state, plan PR. Plans only; does not build. | `<description>` | `clarity-score.py`, `scope-check.py`, `action-items.py`, `handoff-write.py` | `setup`, `run`, `ship`, `autopilot` |
| `/dts2-harness:autopilot` | Run harness steps unattended; a three-provider gate and a council replace the human checkpoints. One branch and PR per step. A short router plus `phase-0-preflight.md` to `phase-4-report.md` and `son-mode.md` (what a headless son reads first). | `<steps>` (section numbers like `3,4,7` or `3-5`, action-item ids, `feature "<text>"`, quoted tasks), `resume`, `status`, `--son <stamp>/<lane>` | `lanes.py`, `checks.py`, `council.py`, `briefs.py`, `roster.py`, `task-ledger.py`, `harness-lock.py`, `action-items.py` | `run`, `ship`, `check-in` |
| `/dts2-harness:dpp` | Run several autopilot lanes in parallel as headless sons, one worktree each, under a head that plans, supervises and serialises merges. | `[dry-run] [--full] [resume]` | `lanes.py`, `plan_graph.py`, `briefs.py`, `checks.py`, `council.py`, `check-in.py`, `task-ledger.py`, `agent-memory.py` | `autopilot` (each son) |
| `/dts2-harness:dpp-full` | `dpp` with `--full`: also fills lanes from a delegation scan and keeps dispatching without a new approval. | no arguments | none of its own | `dpp` |
| `/dts2-harness:fullauto` | `dpp-full` with autopilot forced on, looping check-in until nothing is outstanding. | no arguments | `lanes.py` (`loop`, `stop-check`) | `dpp`, `dpp-full`, `check-in` |
| `/dts2-harness:check-in` | Read-only progress against the approved end state: checklist, `N of M complete`, percent. | no arguments | `check-in.py`, `scope-check.py`, `action-items.py` | `action-items`, `autopilot`, `run`, `setup` |
| `/dts2-harness:model` | Choose which agent provider fills the lead, advisory and sign-off seats; records `lead_provider`. Builders are unaffected. | no arguments | `roster.py`, `delegate.py`, `failover.py` | none |
| `/dts2-harness:find-skills` | Rescan the repo, ask one to three questions, suggest ranked skills, and on a yes add them to the keep list. | no arguments | `env-detect.py`, `repo-size.py`, `scope-check.py`, `skill-suggest.py` | none |

Source for each row: the `description` frontmatter and the usage line in the skill's own `SKILL.md`. The `run` skill also reads `skills/run/modes.md` for `add secret`, `review-pr` and the status lines.

## 2. Agents

Dispatched with the Agent tool as `subagent_type: dts2-harness:<name>`.

| Agent | Role | Tools | Model, turn cap | Scripts it names |
|---|---|---|---|---|
| `dts2-harness:lead` | Read-only planner: slices the end state into a DAG of tasks with exclusive file ownership, picks reviewer axes. Never writes code. | Read, Grep, Glob | opus, 25 | `briefs.py`, `contracts.py`, `delegate.py`, `repo-size.py`, `roster.py` |
| `dts2-harness:builder` | Implements exactly one builder section inside its owned file set; does not review its own work. | Read, Write, Edit, Grep, Glob, Bash | sonnet, 60 | none |
| `dts2-harness:fixer` | Fresh-context fixer for fix round 2 on the same failure: applies the one hypothesis the lead picked (escalation seat, `effort: high`). | Read, Write, Edit, Grep, Glob, Bash | opus, 40 | `delegate.py` |
| `dts2-harness:reviewer` | Read-only reviewer: reviews a diff on one or all axes, returns severity-rated findings and a verdict. | Read, Grep, Glob, Bash | sonnet, 30 | `delegate.py`, `findings.py` |
| `dts2-harness:verifier` | Read-only verifier: runs configured build, type, lint and test commands, checks for stubs, walks changed screens when asked. Evidence only. | all except Write, Edit, NotebookEdit (`disallowedTools`) | opus, 40 | `checks.py` |
| `dts2-harness:scout` | Read-only sizing scout: measures a repo, detects other harnesses and a marketing surface, recommends team tier, builder count and reviewer axes. | Read, Grep, Glob, Bash | haiku, 15 | `repo-size.py`, `deploy-detect.py`, `checks.py` |
| `dts2-harness:auditor` | Read-only machine auditor: inventories installed agent tooling against a blueprint profile and proposes keep, disable and setup. | Read, Grep, Glob, Bash | sonnet, 20 | `env-detect.py`, `machine-prep.py` |

## 3. Hooks

Registered in `hooks/hooks.json`. Every hook script honours the `enabled` setting in `.claude/dts2-harness.local.md` (default true) and, except the guards that deny by design, never fails the session.

| Event (matcher) | Script | What it enforces | Calls | Since |
|---|---|---|---|---|
| SessionStart | `hooks/session-lessons.sh` | Puts the most recent harness lessons (`lessons_max`, default 5, only those whose `paths:` globs match changed files), open state items and open action items into context; after a compact prints a short resume pointer instead. | `scope-check.py --lessons` | changed |
| Stop | `hooks/stop-checks.sh` | Refreshes `.harness/handoff/latest.md`, then a quick typecheck and lint on changed files with `node_modules/.bin/tsc` and `eslint` only (never npx; skipped when absent or the diff is unchanged), under one deadline 5 s below the hook timeout; a timed-out run saves a partial fingerprint. `.harness/checks.sh` is skipped in son mode. Warns on stderr; with `stop_checks_block: true` a red check blocks the stop once (never when `stop_hook_active`). | `handoff-write.py` | changed |
| PostToolUse (`Bash`, `gh pr create *`, `gh pr edit *` and `gh api *`) | `hooks/pr-receipt.sh` | Makes sure the PR body has a `## Change receipt` (receipt picked by the `dts2/<stamp>/` branch, else the newest stamped or `ship-<stamp>` run) and the repo PR template has the section; a `gh api .../pulls -X POST` counts as a PR create. Commits and pushes the template to the PR's own head branch only with `pr_receipt_template_push: true`, never in son mode. Never blocks. | `pr_payload.py` | changed |
| PostToolUse (`Bash\|Edit\|Write\|Agent`) | `hooks/context-guard.sh` | Stops a run on a context spike before the plan checkpoint, or when started in a member repo. Limits: `context_guard_tool_calls` (default 250), `context_guard_mb` (default 12); `context_guard` switches it off. | `context-guard.py` | changed |
| PostToolBatch | `hooks/context-guard.sh` | The same guard, once per batch of parallel tool calls; only the current run's `plan.md` counts as a plan checkpoint. `context_guard_stop: true` adds `continue:false` and a `stopReason` to the guard's output. | `context-guard.py` | new |
| PostToolUse (`SubagentHandback`) | `hooks/subagent-report.sh handback` | Blocks once per agent when a builder, reviewer or verifier report lacks the sections its contract names. | `subagent_report.py --event handback` | new |
| PreToolUse (`Bash`) | `hooks/merge-guard.sh` | Refuses a force-push, and a merge or push to a protected branch unless a lane's `merge-go.md` names the head and base commit. Denials are logged to `.harness/merge-guard.log`. | `guard.py --mode merge` | new |
| PreToolUse (`Bash`, `lanes.py spawn*--dry-run*`) | `hooks/spawn-dry-run.sh` | Prints the composed son brief and exact command, then refuses the call so nothing starts. | `spawn_dry_run.py` | new |
| PreToolUse (`Agent`) | `hooks/spawn-dry-run.sh` | With setting `spawn_dry_run: true`, denies the dispatch and prints the prompt; otherwise passes through. | `spawn_dry_run.py --agent-dry-run` | new |
| PreCompact (`auto\|manual`) | `hooks/pre-compact.sh` | Refreshes `.harness/handoff/latest.md` so the post-compact session can resume from it. | `handoff-write.py` | new |
| SubagentStop (`builder\|reviewer\|verifier`) | `hooks/subagent-report.sh stop` | Same report-section check as the handback hook, on the subagent's last message; skipped when `stop_hook_active`; a report starting `PARTIAL: hit turn cap at <step>` passes. | `subagent_report.py --event stop` | new |
| SessionEnd | `hooks/session-end.sh` | Releases only the lane leases this session took (reasons `logout`, `prompt_input_exit`, `other`), then refreshes the handoff. Lease expiry stays the guarantee. | `session_end.py`, `handoff-write.py` | new |

`hooks/lib-settings.sh` is a shared helper (`setting <field> <default>`), not a registered hook. The son-side deny list is `scripts/guard.py --mode son`, wired into headless sons by `lanes.py spawn`, not through `hooks.json`.

## 4. CLI scripts

Run as `python3 -I "$P/scripts/<x>.py" ...`. Hook-driven and internal scripts are listed too, because each has an argparse entry point. Modules without one are libraries (section 5). Exit codes: 0 ok, 1 a violation or refusal, 2 a failed result (`lanes.py`, `walkthrough_fallback.py`); hook entry points always exit 0.

### 4.1 Project state and progress

| Script | Subcommands and positionals | Key flags | Purpose | Called by | Since |
|---|---|---|---|---|---|
| `action-items.py` | `<repo>` then `list`, `done <row>`, `add <group> <text...>`, `assign <row> <agent>`, `reserve <group> <count>`, `release`, `fold <lane_file>` | `add`: `--id`, `--holder`, `--task`; `reserve`, `release`, `fold`: `--holder` (required) | List and update `.harness/action-items.md`; `reserve`, `release` and `fold` are head-only lane helpers. | `action-items`, `feature`, `check-in`, `learn`, `run`, `autopilot` | |
| `check-in.py` | none | `--items` or `--from` (one required), `--json` | Complete/outstanding checklist against the end state. | `check-in`, `dpp` | |
| `handoff-write.py` | `<repo>` | none | Render `.harness/handoff/latest.md` (state, action items, deploy block, latest receipt, Rollback line); leaves the file alone when the text is unchanged. | `action-items`, `feature`, `ship`, `run`; stop, pre-compact and session-end hooks | changed |
| `lessons.py` | `<repo>` then `promote <lesson>`, `regress <lesson>`, `stats`, `prune` | `promote`: `--lives-at`, `--today`; `regress`: `--today`; `prune`: `--today`, `--stale-days` | Maintain `.harness/lessons.md`: promotions, regressions, pruning of lessons not seen for 90 days. | `learn` | new |
| `metrics.py` | `<repo>` then `append`, `trend` | `append`: `--stamp --rounds --duration --verdict` (required), `--agents`, `--failures`; `trend`: `--last` | Append run metrics (the same stamp twice is one row) and print a trend line. | `learn`, `run` | changed |
| `run_metrics.py` | `plan-check <manifest>`, `record <repo>` | `record`: `--stamp --rounds --duration --verdict --lanes --tokens --wall-clock-s` (required), `--agents`, `--failures`, `--size-class` | Run metrics with lanes, tokens, wall-clock; warns on fewer than two disjoint lanes and on a run above 3x the median tokens. | `lanes.py` at plan time and run end (in-process); by hand | new |
| `run_report.py` | `<run>` (run stamp) | `--runs-dir`, `--repo-url` | Markdown table of one run (lane, status, rounds, cost, wall-clock, PR). Same view as `lanes.py report`. | by hand, for check-ins | new |
| `task-ledger.py` | `<stamp>` | `--cwd`, `--runs-dir`, `--out`, `--resolved` | Open PRs, bundled tasks and the user-input items that block them. | `dpp`, `autopilot` | |
| `scope-check.py` | `[path]` | `--lessons`, `--files` | Detect workspace root, workspace member, single repo or none; with `--lessons` add the newest five lessons whose `paths:` globs match the changed files. Always exits 0. | `feature`, `check-in`, `learn`, `setup`, `run`, `find-skills`; session-lessons hook | changed |
| `clarity-score.py` | `<ratings>` | none | Requirement clarity score; the weakest component bounds it. | `feature`, `setup` | |
| `plan-gate.py` | `<plan>` | `--json` | PASS or FAIL for a lead plan before the checkpoint: Foundation section, exclusive ownership, `complexity:` per builder, token estimate. | `run` | new |
| `state_io.py` | `migrate-all [repo]` | none | Upgrade every record under `.harness/runs/` to the current version; safe to repeat. | by hand | new |
| `settings_cache.py` | `[repo]` | `--get` | Parsed settings from `.harness/config.yaml` and the local frontmatter, cached; `local.son_model` (default `opus`) is the model every dpp son runs on. | by hand | changed |

### 4.2 Repo detection and scaffolding

| Script | Subcommands and positionals | Key flags | Purpose | Called by | Since |
|---|---|---|---|---|---|
| `repo-size.py` | `[repos ...]` | `--max-builders`, `--json` | Size repos and recommend a team tier; `--json` adds `module_lines`, a `heavy` list (500+ lines) and suggested `sections`. | `setup`, `find-skills`; `lead` and `scout` agents | changed |
| `app-type-detect.py` | `<repo>` | `--type` (web-app, api, cli, library, static-site), `--table` | Detect app type and print the readiness table. | `setup` | new |
| `deploy-detect.py` | `<repo>` | none | Detect how a repo deploys, by file presence only. | `setup`, `run`, `evolve`; `scout` agent | |
| `prod-scaffold.py` | `<repo>` | `--app-type` (required), `--no-ci` | Write the CI workflow and production scaffolding; never overwrites. | `setup` | new |
| `ensure-ignored.py` | `<repo>` | `--extra ...` | Append missing harness entries to `.gitignore`. | `setup`, `gtm`, `run` | |
| `agent-memory.py` | none | `--write` (required), `--agents`, `--project` | Give each detected agent a project memory file from one shared source. | `setup`, `run`, `dpp` | |
| `skill-suggest.py` | none | `--facts` | Ranked candidate skill slugs from repo facts. | `find-skills` | |
| `marketing-select.py` | none | `--facts` | Ordered `marketing-skills` subset for the GTM pass. | `gtm` | |
| `skills-check.py` | `<repo>` | `--fix`, `--swap OLD=REF`, `--apply-update NAME=SHA`, `--no-upstream`, `--force-full`, `--home`, `--plugin-root` | Pre-run check of harness version, marketplaces, companion and keep-list skills, with commit pins and proposal-only updates. | `run`, `ship` | changed |
| `upgrade-check.py` | none | `--from-file` (required), `--plugin-json` | Compare the pre-upgrade version with the installed one. | `skills-check.py` (in-process); by hand | |
| `companion-gate.py` | `check`, `record` | `--repo`, `--skill` (required), `check`: `--base` | Run-count gates for two costly companion skills. | `run` | new |
| `env-detect.py` | none (no flags) | none | Report OS, WSL status, which Claude home is live and which agent CLIs are on PATH. Read-only. | `find-skills`, `machine-prep`; `auditor` agent | |

### 4.3 Roster, models and council

| Script | Subcommands and positionals | Key flags | Purpose | Called by | Since |
|---|---|---|---|---|---|
| `roster.py` | `detect`, `resolve`, `probe`, `model`, `command`, `classify` | `detect`: `--project`; `resolve`, `probe`: `--config`; `model`: `--agent --tier`; `command`: `--agent --role`, `--tier`, `--effort`, `--prompt-file`, `--workspace`, `--model`; `classify`: `--agent --role --exit-code`, `--axis`, `--usable` | Detect installed coding agents and resolve the roster into seats; `classify` treats exit 143 as a timeout so a council seat can be swapped. | `model`, `setup`, `run`, `sdk`, `autopilot`; `lead` agent | changed |
| `delegate.py` | none | `--agent --seat --complexity` (required), `--profile-dir`, `--budget`, `--lead-provider`, `--effort` | Resolve model, tier and effort for a dispatch seat (includes the `escalation` seat for the fixer). | `model`, `run`, `onboard`; `lead`, `fixer`, `reviewer` agents | changed |
| `failover.py` | none | `--current` (required), `--profile-dir`, `--exclude` | Pick the next lead provider on a usage or token limit. | `model`, `run` | |
| `seat_swap.py` | `swap`, `identical` | `swap`: `--seats --failed`, `--ledger`, `--step`, `--reason`; `identical`: `--votes-dir --ledger --step --prev --curr` | Council seat substitution and identical-findings ledger note. | `council.py swap` and `identical` (in-process) | new |
| `council.py` | `eligible`, `dossier`, `tally <ballots...>`, `check-decision <decision>`, `route`, `blind`, `wrap <file\|->`, `ledger`, `seats`, `swap`, `identical` | `eligible`: `--votes-dir`; `dossier`: `--votes-dir --out`; `check-decision`: `--tally --entries`, `--ledger`, `--head`; `route`: `--ledger`, `--head`, `--votes`, `--decision` (APPROVE, FIX, STRIKE); `blind`: `--proposals --out --voters --seed`, `--ledger`, `--authors`; `wrap`: `--source`, `--max-chars`; `ledger`: `--ballots-dir --tally --decision --step --stamp --out`; `seats`: `--usable`, `--config`, `--failed`; `swap`: `--seats --failed`, `--ledger`, `--step`, `--reason`; `identical`: `--votes-dir --ledger --step --prev --curr` | Autopilot council: dossier, ballot tally, decision check, routing of red checks to a fix round, blinding, seat substitution and the untrusted-content fence. | `run`, `dpp`, `autopilot` | changed |
| `checks.py` | `run`, `gate`, `summary`, `env-missing <names...>`, `scout-check <file>` | `--stamp` (required for the first four), `--cwd`; `run`: `--base`; `gate`: `--head` | Deterministic checks (tests, types, lint, secret scan, scope) before any model vote, and the run ledger. | `run`, `dpp`, `autopilot`; `verifier` and `scout` agents | new |
| `briefs.py` | `son-brief <manifest>`, `prefix`, `dry-run <manifest>`, `lead-brief` | `son-brief`: `--lane --epoch`, `--max-bundle`, `--out`; `prefix`: `--stamp`, `--cwd`; `dry-run`: `--lane --worktree`, `--cwd`; `lead-brief`: `--stamp`, `--cwd`, `--task-file`, `--roster-json`, `--probe-json` | Son and lead briefs and the cached prompt prefix; starts no process. | `run`, `dpp`, `autopilot`; `lead` agent | new |
| `harness-lock.py` | `<action>` (acquire, release, check) | `--file --holder` (required), `--role` (head or son), `--ttl-sec`, `--lock-dir` | Lock a shared `.harness` record for one writer; only a head may lock. | `autopilot` | changed |

### 4.4 Review and build gates

| Script | Subcommands and positionals | Key flags | Purpose | Called by | Since |
|---|---|---|---|---|---|
| `builder-audit.py` | none | `--base --owned` (required), `--repo`, `--claimed-sha`, `--status`, `--attempt` | Audit one builder's result against its owned files (empty diff with DONE, file outside the owned set, claimed commit not HEAD); read-only. Exit 0 clean, 1 violation. | `run` | new |
| `flags_collect.py` | none | `--stamp --builder` (required), `--repo`, `--report-file` | Collect a builder report's `FLAGS:` block into `flags.md`. | `run` | new |
| `findings.py` | `merge <reports...>`, `digest <reports...>` | `merge`: `--json`; `digest`: `--repo`, `--base` | Merge reviewer findings: calibrate severities by the `DIMENSIONS` table, dedupe by file:line keeping the higher severity; `digest` renders what the final reviewer reads plus `git diff --stat`. | `run`; `reviewer` agent | new |
| `review_split.py` | `plan` | `--base` (required), `--repo`, `--threshold`, `--max-reviewers` | Above a line threshold, split a diff into path-group slices, one reviewer each. Read-only. | `run` | new |
| `rollback_ref.py` | `create`, `line` | `--stamp` (required), `--repo`; `create`: `--sha` | Pin `refs/dts2/<stamp>/base` at the commit a run started from; print the human-run Rollback line. Rolls nothing back. | `run` | new |
| `walkthrough_fallback.py` | none | `--out`, `--url` (repeatable) (required), `--cwd` | Playwright fallback for the post-merge walkthrough: sandbox only, host allowlist, no `file://`; skipped without Playwright. | `run` | new |

### 4.5 Parallel lanes (dpp)

`lanes.py` is the only writer of lane state. It is a thin CLI over the `scripts/lanes/` package (see `ARCHITECTURE.md`). Global flags go before the subcommand: `--runs-dir`, `--cwd`, `--no-prs` (skip the open-PR check on purpose). Output is one JSON object; exit 0 when `ok`, 1 on a `LaneError`, 2 on a not-ok result. A son (`DTS2_SON=1`) is refused by `merge-go`, `merge-go-step`, `merge-target` and `gc-restore`.

Manifest-keyed commands:

| Subcommand | Arguments and flags | Purpose | Called by | Since |
|---|---|---|---|---|
| `check <manifest>` | none | Overlap check on a lane manifest, plus the plan-graph checks of `plan_graph.py` (contracts, owners, cycles, critical path); advisory. | `dpp`, `run` | changed |
| `lease <manifest>` | `--lane` (required), `--epoch` | Take a lane lease (fails closed without `gh` unless `--no-prs`; leases expire and a heartbeat renews them). | `dpp` | changed |
| `amend <manifest>` | `--lane` (required); `--set-files`, `--add-files`, `--remove-files`, `--depends-on`, `--provides`, `--consumes`, `--stubbed-on`, `--merge-after` (comma separated) | Change one lane of a running manifest, re-check, bump the epoch, rewrite `brief.md`. | `dpp` | new |
| `son-command <manifest>` | `--lane --worktree` (required) | Print the son command line. | `lanes.py spawn` (in-process) | |
| `spawn <manifest>` | `--lane --worktree` (required), `--resume`, `--unsafe-no-sandbox` | Start a son under every cap (turns, spend, model-call limit, sandbox). | `dpp`, `autopilot`; spawn-dry-run hook | new |
| `merge-order <manifest>` | none | Print merge order and who is next. | `dpp` | new |
| `merge-plan <manifest>` | `--base` | Merge queue or serial rebase-test-merge plan; `git merge-tree --write-tree` probe of every lane; integration lane last. Merges nothing. | `run`, `dpp` | new |
| `merge-go <manifest>` | `--lane --head` (required), `--base` | Write `merge-go.md` for a verified head and base commit (head only). | `dpp`, `autopilot` | new |
| `audit <manifest> <lane>` | `--head` (required), `--base` | List files the lane branch changed outside its owned set; the same ownership check `merge-go` runs before it grants a merge. Read-only. | `dpp`, `autopilot` | new |
| `merge-resume <manifest>` | none | Settle a merge a dead head left half done, by asking GitHub. | none yet | new |
| `merge-done <manifest>` | `--lane` (required) | Mark a lane merged; when all are merged restore `gc.auto` and record the run end. | `dpp` | new |

Stamp-keyed commands:

| Subcommand | Arguments and flags | Purpose | Called by | Since |
|---|---|---|---|---|
| `plan` | `--from-checkin --draft` (required), `--outside`, `--full`, `--max`, `--stamp`, `--autopilot`, `--fullauto` | Admit lanes, add spend estimates, feasibility, a `graph` block (cycle check, critical path), `--full` selection. | `dpp`, `run` | changed |
| `status <stamp>` | none | Lane status, heartbeat and stall marks. | `dpp`, `autopilot` | changed |
| `sendback <stamp>` | `--lane --reason` (required) | Send a lane back (counted atomically, at most two). | `dpp` | changed |
| `release <stamp>` | `--lane` (required), `--epoch` | Release a lane; a stale epoch is refused. | `dpp` | changed |
| `fold <stamp>` | none | Fold lane results into named groups, one PR each. | `dpp` | changed |
| `fold-done <stamp>` | `--group` (required), `--pr` | Record that a fold group's PR is shipped. | none yet | new |
| `stop-check <stamp>` | `--from-checkin` (required), `--base` | Whether fullauto may stop; items tied to a ledgered blocked PR do not count; `--base` reads the end state from the fetched `origin/<base>`. | `fullauto` | changed |
| `approve-lane <stamp>` | `--lane` (required) | Record the user's yes for one lane (`dpp_full_ask_each_lane`); `lease` refuses a lane without it. Head only. | `dpp` | new |
| `override <lane>` | `--reason` (required) | The owner's override of a lane rule, logged to `state.md`; refused in a son, a vote or the council, and without the human approval channel. | none yet | new |
| `mailbox <op> <stamp>` | `op` (ask, need-human, answer, check, wait, park, merge-go-check, rules, request, decide); `--lane` (required), `--id`, `--text`, `--reason`, `--session-id`, `--point`, `--files`, `--outcome`, `--epoch`, `--worktree` | The head/son mailbox: versioned question, answer, need-human, send-back and merge-go messages with a deadline (`mailbox_wait_min`) and a park on expiry; the son's merge-go HEAD check; rule re-read digests; the out-of-lane ladder. | `autopilot --son`, `dpp` | new |
| `branch-check <stamp>` | `--lanes` (required, comma-separated) | Branch-name collision check. | none (internal) | |
| `preflight <stamp>` | none | Pin the CLI version and test the real son launch. | `dpp` | new |
| `budget <stamp>` | none | Budget report. | `dpp` | new |
| `loop <stamp>` | none | Fullauto loop cap. | `fullauto` | new |
| `call <stamp>` | `--label` (required), `--timeout`, `--cost-source` (claude or none), `--prompt-file`, `--out`; command follows `--` | Any other model call behind the shared limit. | `autopilot` | new |
| `heartbeat <stamp>` | `--lane` (required), `--epoch`, `--turn`, `--status` (pr-open, done, blocked, incomplete), `--reason`, `--blocked-by` | Record a lane heartbeat or phase (goes through `transition`). | `autopilot`; son brief | new |
| `merge-target <stamp>` | `--set`, `--yes-default-branch` | Record the branch the run merges into (head only). | `dpp`, `autopilot` | new |
| `merge-go-step <stamp>` | `--step --head` (required), `--base` | Merge clearance for an autopilot step (head only). | `autopilot` | new |
| `gc-restore <stamp>` | none | Restore `gc.auto` after an aborted run (head only). | `dpp` | new |
| `wait <stamp>` | `--timeout` (seconds, hard deadline, default 600) | Block until a lane's phase or `exit.json` changes (inotify when the kernel has it, else a sleep-backoff loop), then return which lanes moved; the head calls it once instead of polling `status`. | `dpp` | new |
| `gc` | none | Close expired leases of lanes nobody is running (a crashed run's); `preflight` and `spawn --resume` run it too. | `dpp` | new |
| `transition <stamp>` | `--lane --to` (required; one of starting, pr-open, done, blocked, incomplete, orphaned), `--epoch`, `--reason`, `--blocked-by`, `--turn` | The one writer of a lane's phase, checked against the table of legal moves; a son may report only pr-open, done, blocked, incomplete. | none yet (`heartbeat`, park and spawn call it) | new |
| `shutdown <stamp>` | `--grace-s` | Graceful end of a run: park running lanes, stop sons (SIGTERM, then SIGKILL after the grace period), close leases, restore `gc.auto`. | none yet | new |
| `reconcile <stamp>` | none | Ask GitHub what exists for each lane before creating, merging or resuming; returns one action per lane (a lane whose son exited, or that stalled, is also moved to incomplete here); fails closed without `gh`. | none yet | new |
| `run-record <stamp>` | `--init`, `--kind` (run or autopilot) | Open or print the run's typed record (`run.json`). | none yet | new |
| `builder <stamp>` | `--lane --section --branch --status` (required; status is a lane phase or merged), `--round`, `--sha`, `--pr`, `--base` | Append one builder row to `builders.jsonl`; the sha is confirmed against the branch tip and diff. | none yet | new |
| `run-resume <stamp>` | none | What `run resume` reads: the run record and the newest row of each builder. | none yet | new |
| `walkthrough-failed <stamp>` | `--lane --reason` (required) | Record a failed post-merge walkthrough and file one revert action item. | none yet | new |
| `report <stamp>` | `--repo-url` | The run as a markdown table plus run-wide sections: refusals, overrides, merge order and rebases, total spend, check-in delta, per-son CI result, merge commit and out-of-lane requests. | none yet | changed |
| `report-check <report>` | `--lanes` (required), `--stamp` | Check the final report against lane ids; with `--stamp` also cross-check the son run records (unlisted lanes, PRs the report never names). | `dpp` | |

"None yet" means no skill or hook text calls the command in 3.10.0: the head can run it by hand, and the lifecycle commands are the API a later skill change is meant to wire in.

### 4.6 Maintenance and diagnostics

| Script | Subcommands and positionals | Key flags | Purpose | Called by | Since |
|---|---|---|---|---|---|
| `doctor.py` | none | `--json` | Preflight checks for this machine. | `make doctor` | new |
| `machine-prep.py` | `audit`, `plan`, `apply` | `--profile`, `--home`, `--claude-home`, `--tier`, `--days`, `--project` | Audit a machine against a blueprint profile; `apply` prunes plugins by disabling them (reversible). | `machine-prep`; `auditor` agent | |
| `usage-scan.py` | none | `--claude-home` (required), `--days` | Count Skill, Agent and MCP tool uses in recent transcripts; read-only. | `machine-prep.py` (in-process) | |
| `context-tax.py` | none | `--root`, `--budget`, `--max-description` | Measure always-loaded skill and agent metadata; exit 1 over budget. | CI `metadata` job | new |
| `bump-version.py` | `<version>` | `--root`, `--check` | Bump or verify the version in the four places it is recorded. | `make check-version` | new |
| `changelog-join.py` | none | `--root`, `--version`, `--apply`, `--date` | Join `changelog.d/` fragments into the README changelog; dry run unless `--apply`. | release step | new |

### 4.7 Hook entry points (called by hooks, usable by hand)

| Script | Arguments | Purpose | Called by | Since |
|---|---|---|---|---|
| `context-guard.py` | `--tool-calls --mb` (required); hook JSON on stdin | PostToolUse context guard. | context-guard hook | new |
| `guard.py` | `--mode son\|merge` (required), `--cwd`; hook JSON on stdin | PreToolUse son deny list and merge gate. | merge-guard hook (`merge`); `lanes.py spawn` wires `son` | new |
| `subagent_report.py` | `--event stop\|handback` (required); hook JSON on stdin | Report-section check. | subagent-report hook | new |
| `spawn_dry_run.py` | `--agent-dry-run`; hook JSON on stdin | Print the composed brief and command, start nothing. | spawn-dry-run hook | new |
| `session_end.py` | hook JSON on stdin (no flags) | Release the lane leases this session took. | session-end hook | new |
| `pr_payload.py` | `parse`, `view --body-out`, `body --body-file --receipt-file`, `payload [pairs...]` | Payload helpers for the PR-receipt hook. | pr-receipt hook | new |

### 4.8 Other entry points

| Script | Arguments | Purpose | Called by | Since |
|---|---|---|---|---|
| `plan_graph.py` | `analyse <manifest>`, `merge-order <manifest> --runs-dir D`, `brief <manifest> --lane L`; global `--cwd` | Plan graph for a lane manifest: `provides`/`consumes`/`stubbed_on` contracts, prefix and glob owners, package-root areas, cycle check, critical path. `analyse` prints the report, `merge-order` records the provider-first order, `brief` prints the six-section lane brief. Read-only except `merge-order`. | `run`, `dpp`; `lanes.py check`, `lease`, `plan` (in-process) | new |
| `protected.py` | `<repo> paths`, `<repo> check [names...]` | | Protected paths a son's diff must not touch (git common dir config/info/hooks, `.gitattributes`, workflows, checks script, CODEOWNERS, `hooks/`, head-only `.harness` records, `merge-go.md`); a touching diff parks as a Decisions item. | `head_publish.py`; `dpp` | new |
| `approvals.py` | `--repo`; `check <kind> <key> [--session]`, `path` | | Human-only approval channel: `dts2_approvals` in `.claude/settings.local.json`, which the model cannot write; logs the asker as `human` or `agent:<session>`. | `head_publish.py`; `dpp`, `autopilot` | new |
| `head_publish.py` | `--repo`; `publish --lane --branch --base --title [--body]`, `merge <pr> [--verifier-ok --default-branch --deploys-production]`, `bootstrap --stamp --lane --worktree` | | The head pushes and opens one PR per lane, merges when the preconditions hold (checks reported and green, protection or queue, a per-PR yes for a production deploy) and bootstraps each lane (install once, sanitized `son.env`, missing secrets filed). Intended `lanes.py publish`. | `dpp`, `autopilot` (head only) | new |
| `provider_report.py` | `footer`, `check <file\|->` | | Provider-neutral brief footer and validator for the fenced JSON report every non-Claude seat ends with. | `run`, `autopilot` | new |
| `ballot_dispatch.py` | `dispatch --seat --model --prompt-file --out-dir [--provider] [-- argv]` | | Runs one council seat through the shared call limit and writes the ballot with its `.dispatch.json` record (argv, model, session id, sha256); Claude seats use `--json-schema` and `--restricted`. | `autopilot` council | new |
| `sdk/dts2-run.py` | `<task>`; `--repo`, `--yes`, `--api-key-env`, `--second-opinion none\|codex\|gemini`, `--ship`, `--live-only` | Headless pipeline on the Agent SDK. | `sdk` | |
| `evals/run.py` | `--fixture` (repeatable), `--baseline`, `--results-dir`, `--update-baseline` | Run the smoke-eval fixtures against the baseline. | by hand | new |

## 5. Library modules (no command line)

Imported by the scripts above; none is a CLI. Responsibilities are in `ARCHITECTURE.md`.

`_load.py`, `contracts.py`, `mdparse.py`, `miniyaml.py`, `model_call.py`, `ownership_audit.py`, `prep-tiers.py` (helper for `machine-prep.py`), `proc.py` (also the son lifecycle: `wrap_son`, `son.json`, `exit.json`, SIGINT-then-SIGKILL), `profiles.py`, `skill_pins.py`, `son_launch.py` (also `provider_env`, `allowed_tools`, `auth_problem`, `init_plugin_errors`), `son_stream.py` (stream-json heartbeat, `detect_stuck`, `api_retry` exhaustion), `state_ids.py`, and the modules of `scripts/lanes/` (`amend`, `common`, `conflicts`, `gitrefs`, `integration`, `journal`, `leases`, `merge`, `mergeplan`, `mergeresume`, `phases`, `planner`, `reconcile`, `records`, `runend`, `runrecord`, `runstate`, `shutdown`, `supervisor`, `waiter`).

## 6. Makefile targets and CI

Defined in the repository root `Makefile` (one level above the plugin directory).

| Target | What it runs | Since |
|---|---|---|
| `make package` | Builds `dist/dts2-harness-<version>.zip` and `dist/dts2-marketplace-<version>.zip` with `git archive`. | new |
| `make test` | `cd plugins/dts2-harness && python3 -m unittest discover -s tests`. | new |
| `make check-version` | `bump-version.py <version> --check` against `plugin.json`. | new |
| `make doctor` | `python3 plugins/dts2-harness/scripts/doctor.py`. | new |

CI (`.github/workflows/test.yml`) runs the unittest suite on Python 3.10 to 3.13, `ruff check plugins/dts2-harness`, `shellcheck -x` on the hooks, `context-tax.py`, and `claude plugin validate plugins/dts2-harness --strict`.

## 7. Changed in 3.10.0

Sources: `changelog.d/*.md`, the `## Unreleased` lines in `README.md`, and `git log --oneline 0f254f8^..HEAD` (the 3.9.1 release is the base). Ids such as G-13 are the batch ids used in those files.

### 7.1 New commands

| What | Commands | Source |
|---|---|---|
| Lane lifecycle | `lanes.py transition`, `shutdown`, `reconcile`, `run-record`, `builder`, `run-resume`, `fold-done`, `merge-resume`, `walkthrough-failed`, `report` | G-13, G-14, G-15, G-17, N6 |
| Lane supervisor and merge | `lanes.py spawn`, `call`, `heartbeat`, `preflight`, `budget`, `loop`, `merge-order`, `merge-plan`, `merge-go`, `merge-target`, `merge-go-step`, `merge-done`, `gc-restore`, `wait`, `gc` | A4, A5, A6, A11, N1, N2, B6, Q-15, G-18 |
| Plan graph | `lanes.py amend`; `plan_graph.py analyse`, `merge-order`, `brief` | G-26, G-27, G-28, G-29, Q-22 |
| Review and build gates | `builder-audit.py`, `plan-gate.py`, `flags_collect.py`, `findings.py merge\|digest`, `review_split.py plan`, `rollback_ref.py create\|line` | AA-1, AA-5, AA-9, Q-21, AA-7, AA-10 |
| Council | `council.py route`, `blind`, `wrap`, `swap`, `identical`; `seat_swap.py` | B2, A9, B7 |
| Checks and briefs | `checks.py run\|gate\|summary\|env-missing\|scout-check`; `briefs.py son-brief\|prefix\|dry-run\|lead-brief` | A12, N3, B5, B1, N5, Q-11 |
| Lessons and metrics | `lessons.py promote\|regress\|stats\|prune`; `run_metrics.py plan-check\|record`; `run_report.py` | Q-5, Q-6, SE-1, N6 |
| Setup and production | `app-type-detect.py`, `prod-scaffold.py`, `companion-gate.py` | C1 to C7, B4 |
| Release and CI | `bump-version.py`, `changelog-join.py`, `context-tax.py`, `doctor.py`, `state_io.py migrate-all`, `settings_cache.py`, `walkthrough_fallback.py`, `evals/run.py`, Makefile targets, CI workflow | B9, Q-1, Q-18, N7, G-9, G-22, B10, B1/N4, A1 |
| Hooks | `merge-guard.sh`, `pre-compact.sh`, `session-end.sh`, `spawn-dry-run.sh`, `subagent-report.sh` | Q-15, Q-7, Q-16, Q-8 |
| Agent | `dts2-harness:fixer` (the `escalation` seat in `delegate.py`) | AA-4 |

### 7.2 Changed commands

| Command | What changed | Source |
|---|---|---|
| `lanes.py check`, `lease`, `plan` | Run the plan-graph checks; owners may be `dir/` prefixes or globs; routing of lockfiles, migrations, route tables, barrels and `lanes.shared_files` to a final integration lane (a PR bundles at most 5 tasks); `lease` and `plan` fail closed without `gh`; leases carry `expires_at` and `ttl_s`, take the check and the write under one admission lock, and record `session_id`; `plan` adds spend estimates and a `graph` block | G-20, G-16, G-25, B6, G-26 to G-28, Q-22 |
| `lanes.py release`, `sendback`, `status`, `fold` | `release` refuses a stale `--epoch`; the epoch is mandatory in the state port; send-backs are counted atomically; `status` shows heartbeat and stalls; `fold` names each group | G-11, N2, G-15 |
| `lanes/mailbox.py`, `lanes/policy.py` | The head/son mailbox and message schema (G-43 to G-45, G-48, G-49); approval and scope policy: override, ask-each-lane, frozen scope, end state from `origin/<base>` (G-46, G-48, G-50) | G-43 to G-51 |
| `lanes.py` as a whole | Now a thin CLI over the `scripts/lanes/` package; phase writes all go through `transition` | AC-3, G-13 |
| `council.py` | Strict verdict first line on `tally`; seats may be swapped on timeout; identical findings leave a ledger note | A9, B7 |
| `roster.py classify` | Exit 143 is a timeout with `seatFailed: true` | roster-143 |
| `delegate.py` | Owns the complexity policy; new `escalation` seat | AC-2, AA-4 |
| `repo-size.py --json` | Adds `module_lines`, `heavy` and suggested `sections`; `max_builders` defaults to 4 | AA-2, SE-2 |
| `handoff-write.py` | Skips the write when the text is unchanged; copies the Rollback line | Q-9, AA-10 |
| `scope-check.py` | New `--lessons` and `--files` | Q-5 |
| `skills-check.py` | New `--apply-update`; commit pins in `keep.yaml`; proposal-only updates | B4 |
| `metrics.py` | One row per stamp (idempotent event ids) | G-23 |
| `harness-lock.py` | Lock file is created complete (temp file plus `os.link`) | nits |
| Skills `autopilot`, `setup`, `run` | Router `SKILL.md` plus phase files read on demand; the run plan needs a `## Foundation` section (wave 0); mechanical sections go to a haiku builder; fix round 2 goes to the `fixer` | Q-10, B1, AA-3, AA-8, AA-4 |
| Hooks `session-lessons.sh`, `stop-checks.sh`, `pr-receipt.sh`, `context-guard.sh` | Path-scoped lessons and compact resume pointer; unchanged-diff skip; `if` filters on `gh pr create\|edit`, payload parsing in `pr_payload.py`; one Python process per call | Q-5, Q-7, Q-13, AC-5, A10 |
