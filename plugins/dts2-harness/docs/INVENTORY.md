# dts2-harness command inventory

Generated for 3.10.0; batches 13/14B/nits pending merge may add commands.

Every entry is sourced from the files in this plugin: `skills/*/SKILL.md`, `agents/*.md`, `hooks/hooks.json` and `hooks/*.sh`, the argparse definitions in `scripts/*.py`, and the root `Makefile`. In examples, `$P` stands for `${CLAUDE_PLUGIN_ROOT}` and `<repo>` for a repo root.

## 1. Skills (slash commands)

Invoke as `/dts2-harness:<name>`. Skills with `disable-model-invocation: true` in their frontmatter (`dpp-full`, `fullauto`, `machine-prep`, `model`, `onboard`, `sdk`) run only when the user types them.

| Command | Purpose | Usage and arguments | Example |
|---|---|---|---|
| `/dts2-harness:onboard` | Explain the harness (agents, skills, roster, tiers, lessons, headless runner) and recommend where to start. Explanation only; changes nothing. | no arguments | `/dts2-harness:onboard` |
| `/dts2-harness:machine-prep` | Scan this computer's agent tooling, compare to the blueprint profile, prune by disabling, set up the slim startup. | no arguments; drives `machine-prep.py audit\|plan\|apply` | `/dts2-harness:machine-prep` |
| `/dts2-harness:setup` | Interview to an approved end state (`.harness/end-state.md`), then scaffold harness config in one repo, many repos or a workspace. | `[path ...] [--scaffold-only]`; several paths means batch (scaffold only) | `/dts2-harness:setup --scaffold-only` |
| `/dts2-harness:run` | Plan, build, review and verify pipeline on a task in one repo or workspace; ends with a receipt. | `<task>`, `resume`, `section <#>`, `add secret NAME`, `review-pr <number>` | `/dts2-harness:run add secret STRIPE_KEY` |
| `/dts2-harness:learn` | Consolidate reviewer and verifier findings into `.harness/lessons.md`; prune stale lessons. | no arguments, or `promote <L-NNN>` | `/dts2-harness:learn` |
| `/dts2-harness:sdk` | Set up and run the pipeline headless with the Agent SDK (CI, cron, servers, WSL). | no arguments; runs `sdk/dts2-run.py` (section 5) | `/dts2-harness:sdk` |
| `/dts2-harness:evolve` | Change the harness itself in its source repo: edit, validate, test, bump versions, commit; push only on an explicit yes. | no arguments, or `deploy` to change the repo's deploy target | `/dts2-harness:evolve deploy` |
| `/dts2-harness:action-items` | Show open Secrets, Decisions, Handoff, Deploy and Promotions items with age, owner and resolving command; mark done, add, assign. | no arguments (list), or the `done`, `add`, `assign` subcommands | `/dts2-harness:action-items` |
| `/dts2-harness:gtm` | Go-to-market in one pass: installs `marketing-skills` if missing, runs a deep-dive and applicable skills, ends with a readiness scorecard. | no arguments | `/dts2-harness:gtm` |
| `/dts2-harness:ship` | Ship the current branch as a pull request: pre-check, repo checks, secret scan, verifier and reviewer, receipt, push, open PR; then sweep stale branches and PRs. Never merges. | `[base]`; base defaults to `dev` when it exists on the remote, else the default branch | `/dts2-harness:ship main` |
| `/dts2-harness:feature` | Add a feature to the roadmap: clarity score, interview when unclear, lead writes it into the end state, plan PR. Plans only; does not build. | `<description>` | `/dts2-harness:feature "export reports as CSV"` |
| `/dts2-harness:autopilot` | Run harness steps unattended; a three-provider gate and a council replace the human checkpoints. One branch and PR per step. | `<steps>` (section numbers like `3,4,7` or `3-5`, action-item ids, `feature "<text>"`, quoted tasks), `resume`, `status`, `--son <stamp>/<lane>` | `/dts2-harness:autopilot 3-5` |
| `/dts2-harness:dpp` | Run several autopilot lanes in parallel as headless sons, one worktree each, under a head that plans, supervises and serialises merges. | `[dry-run] [--full] [resume]` | `/dts2-harness:dpp dry-run` |
| `/dts2-harness:dpp-full` | `dpp` with `--full`: also fills lanes from a delegation scan and keeps dispatching without a new approval. | no arguments | `/dts2-harness:dpp-full` |
| `/dts2-harness:fullauto` | `dpp-full` with autopilot forced on, looping check-in until nothing is outstanding. | no arguments | `/dts2-harness:fullauto` |
| `/dts2-harness:check-in` | Read-only progress against the approved end state: checklist, `N of M complete`, percent. | no arguments | `/dts2-harness:check-in` |
| `/dts2-harness:model` | Choose which agent provider fills the lead, advisory and sign-off seats; records `lead_provider`. Builders are unaffected. | no arguments | `/dts2-harness:model` |
| `/dts2-harness:find-skills` | Rescan the repo, ask one to three questions, suggest ranked skills, and on a yes add them to the keep list. | no arguments | `/dts2-harness:find-skills` |

Source for each row: the `description` frontmatter and the usage line in the skill's own `SKILL.md`. The `run` skill also reads `skills/run/modes.md` for `add secret`, `review-pr` and the status lines.

## 2. Agents

Dispatched with the Agent tool as `subagent_type: dts2-harness:<name>`.

| Agent | Role | Tools | Model, turn cap |
|---|---|---|---|
| `dts2-harness:lead` | Read-only planner: slices the end state into a DAG of tasks with exclusive file ownership, picks reviewer axes. Never writes code. | Read, Grep, Glob | opus, 25 |
| `dts2-harness:builder` | Implements exactly one builder section inside its owned file set; does not review its own work. | Read, Write, Edit, Grep, Glob, Bash | sonnet, 60 |
| `dts2-harness:reviewer` | Read-only reviewer: reviews a diff on one or all axes, returns severity-rated findings and a verdict. | Read, Grep, Glob, Bash | sonnet, 30 |
| `dts2-harness:verifier` | Read-only verifier: runs configured build, type, lint and test commands, checks for stubs, walks changed screens when asked. Evidence only. | all except Write, Edit, NotebookEdit (`disallowedTools`) | opus, 40 |
| `dts2-harness:scout` | Read-only sizing scout: measures a repo, detects other harnesses and a marketing surface, recommends team tier, builder count and reviewer axes. | Read, Grep, Glob, Bash | haiku, 15 |
| `dts2-harness:auditor` | Read-only machine auditor: inventories installed agent tooling against a blueprint profile and proposes keep, disable and setup. | Read, Grep, Glob, Bash | sonnet, 20 |

## 3. Hooks

Registered in `hooks/hooks.json`. Every hook script honours the `enabled` setting in `.claude/dts2-harness.local.md` (default true) and, except the guards that deny by design, never fails the session.

| Event (matcher) | Script | What it enforces |
|---|---|---|
| SessionStart | `hooks/session-lessons.sh` | Puts the most recent harness lessons (`lessons_max`, default 5), open state items and open action items into context. |
| Stop | `hooks/stop-checks.sh` | Refreshes `.harness/handoff/latest.md`, then a quick typecheck and lint on changed files. Non-blocking; warnings go to stderr. |
| PostToolUse (`Bash`, `gh pr create *` and `gh pr edit *`) | `hooks/pr-receipt.sh` | Makes sure the PR body has a `## Change receipt` and the repo PR template has the section; pushes only the PR's own head branch. Never blocks. |
| PostToolUse (`Bash\|Edit\|Write\|Agent`) | `hooks/context-guard.sh` | Stops a run on a context spike before the plan checkpoint, or when started in a member repo. Limits: `context_guard_tool_calls` (default 250), `context_guard_mb` (default 12); `context_guard` switches it off. |
| PostToolUse (`SubagentHandback`) | `hooks/subagent-report.sh handback` | Blocks once per agent when a builder, reviewer or verifier report lacks the sections its contract names. |
| PreToolUse (`Bash`) | `hooks/merge-guard.sh` | Refuses a force-push, and a merge or push to a protected branch unless a lane's `merge-go.md` names the head and base commit. Denials are logged to `.harness/merge-guard.log`. Decided by `scripts/guard.py --mode merge`. |
| PreToolUse (`Bash`, `lanes.py spawn*--dry-run*`) | `hooks/spawn-dry-run.sh` | Prints the composed son brief and exact command, then refuses the call so nothing starts. |
| PreToolUse (`Agent`) | `hooks/spawn-dry-run.sh` | With setting `spawn_dry_run: true`, denies the dispatch and prints the prompt; otherwise passes through. |
| PreCompact (`auto\|manual`) | `hooks/pre-compact.sh` | Refreshes `.harness/handoff/latest.md` so the post-compact session can resume from it. |
| SubagentStop (`builder\|reviewer\|verifier`) | `hooks/subagent-report.sh stop` | Same report-section check as the handback hook, on the subagent's last message; skipped when `stop_hook_active`. |
| SessionEnd | `hooks/session-end.sh` | Releases only the lane leases this session took (reasons `logout`, `prompt_input_exit`, `other`), then refreshes the handoff. Lease expiry stays the guarantee. |

`hooks/lib-settings.sh` is a shared helper (`setting <field> <default>`), not a registered hook. The son-side deny list is `scripts/guard.py --mode son`, wired into headless sons by `lanes.py spawn`, not through `hooks.json`.

## 4. CLI scripts

Run as `python3 "$P/scripts/<x>.py" ...`. The hook-driven and internal-only scripts are listed too, because each has an argparse entry point. Libraries without one (`_load`, `contracts`, `mdparse`, `miniyaml`, `model_call`, `ownership_audit`, `proc`, `profiles`, the `lanes/` package modules, `session_end`, `skill_pins`, `son_launch`, `state_ids`) are not CLIs.

### 4.1 Project state and progress

| Script | Subcommands and positionals | Key flags | Purpose |
|---|---|---|---|
| `action-items.py` | `<repo>` then `list`, `done <row>`, `add <group> <text...>`, `assign <row> <agent>`, `reserve <group> <count>`, `release`, `fold <lane_file>` | `add`: `--id`, `--holder`, `--task`; `reserve`, `release`, `fold`: `--holder` (required) | List and update `.harness/action-items.md`; `reserve`, `release` and `fold` are head-only lane helpers. |
| `check-in.py` | none | `--items`, `--from`, `--json` | Complete/outstanding checklist against the end state. |
| `handoff-write.py` | `<repo>` | none | Render `.harness/handoff/latest.md`. |
| `lessons.py` | `<repo>` then `promote <lesson>`, `regress <lesson>`, `stats`, `prune` | `promote`: `--lives-at`, `--today`; `regress`: `--today`; `prune`: `--today`, `--stale-days` | Maintain `.harness/lessons.md`. |
| `metrics.py` | `<repo>` then `append`, `trend` | `append`: `--stamp --rounds --duration --verdict` (required), `--agents`, `--failures`; `trend`: `--last` | Append run metrics and print a trend line. |
| `run_metrics.py` | `plan-check <manifest>`, `record <repo>` | `record`: `--stamp --rounds --duration --verdict --lanes --tokens --wall-clock-s` (required), `--agents`, `--failures`, `--size-class` | Run metrics with lanes, tokens, wall-clock; warns on fewer than two disjoint lanes. |
| `run_report.py` | `<run>` (run stamp) | `--runs-dir`, `--repo-url` | Markdown table of one run (lane, status, rounds, cost, wall-clock, PR). |
| `task-ledger.py` | `<stamp>` | `--cwd`, `--runs-dir`, `--out`, `--resolved` | Open PRs, bundled tasks and the user-input items that block them. |
| `scope-check.py` | `[path]` | `--lessons`, `--files` | Detect workspace root, workspace member, single repo or none; always exits 0. |
| `clarity-score.py` | `<ratings>` | none | Requirement clarity score; the weakest component bounds it. |
| `plan-gate.py` | `<plan>` | `--json` | PASS or FAIL for a lead plan before the checkpoint. |
| `state_io.py` | `migrate-all [repo]` | none | Upgrade every record under `.harness/runs/` to the current version. |

### 4.2 Repo detection and scaffolding

| Script | Subcommands and positionals | Key flags | Purpose |
|---|---|---|---|
| `repo-size.py` | `[repos ...]` | `--max-builders`, `--json` | Size repos and recommend a team tier. |
| `app-type-detect.py` | `<repo>` | `--type` (web-app, api, cli, library, static-site), `--table` | Detect app type and print the readiness table. |
| `deploy-detect.py` | `<repo>` | none | Detect how a repo deploys, by file presence only. |
| `prod-scaffold.py` | `<repo>` | `--app-type` (required), `--no-ci` | Write the CI workflow and production scaffolding. |
| `ensure-ignored.py` | `<repo>` | `--extra ...` | Append missing harness entries to `.gitignore`. |
| `agent-memory.py` | none | `--write` (required), `--agents`, `--project` | Give each detected agent a project memory file from one shared source. |
| `skill-suggest.py` | none | `--facts` | Ranked candidate skill slugs from repo facts. |
| `marketing-select.py` | none | `--facts` | Ordered `marketing-skills` subset for the GTM pass. |
| `skills-check.py` | `<repo>` | `--fix`, `--swap`, `--apply-update`, `--no-upstream`, `--force-full`, `--home`, `--plugin-root` | Pre-run check of harness version, marketplaces, companion and keep-list skills. |
| `upgrade-check.py` | none | `--from-file` (required), `--plugin-json` | Compare the pre-upgrade version with the installed one. |
| `companion-gate.py` | `check`, `record` | `--repo`, `--skill` (required), `check`: `--base` | Run-count gates for two costly companion skills. |

### 4.3 Roster, models and orchestration

| Script | Subcommands and positionals | Key flags | Purpose |
|---|---|---|---|
| `roster.py` | `detect`, `resolve`, `probe`, `model`, `command`, `classify` | `detect`: `--project`; `resolve`, `probe`: `--config`; `model`: `--agent --tier`; `command`: `--agent --role`, `--tier`, `--effort`, `--prompt-file`, `--workspace`, `--model`; `classify`: `--agent --role --exit-code`, `--axis`, `--usable` | Detect installed coding agents and resolve the roster into seats. |
| `delegate.py` | none | `--agent --seat --complexity` (required), `--profile-dir`, `--budget`, `--lead-provider`, `--effort` | Resolve model, tier and effort for a dispatch seat. |
| `failover.py` | none | `--current` (required), `--profile-dir`, `--exclude` | Pick the next lead provider on a usage or token limit. |
| `seat_swap.py` | `swap`, `identical` | `swap`: `--seats --failed`, `--ledger`, `--step`, `--reason`; `identical`: `--votes-dir --ledger --step --prev --curr` | Council seat substitution and identical-findings ledger note. |
| `council.py` | `eligible`, `dossier`, `tally <ballots...>`, `check-decision <decision>`, `route`, `blind`, `wrap <file>`, `ledger`, `seats`, `swap`, `identical` | `eligible`: `--votes-dir`; `dossier`: `--votes-dir --out`; `check-decision`: `--tally --entries`, `--ledger`, `--head`; `route`: `--ledger`, `--head`, `--votes`, `--decision` (APPROVE, FIX, STRIKE); `blind`: `--proposals --out --voters --seed`; `wrap`: `--source`; `ledger`: `--ballots-dir --tally --decision --step --stamp --out`; `seats`: `--usable`, `--config`, `--failed` | Autopilot council: dossier, ballot tally, decision check, blinding and the untrusted-content fence. |
| `checks.py` | `run`, `gate`, `summary`, `env-missing <names...>`, `scout-check <file>` | `--stamp` (required for the first four), `--cwd`; `run`: `--base`; `gate`: `--head` | Deterministic checks before any model vote, and the run ledger. |
| `briefs.py` | `son-brief <manifest>`, `prefix`, `dry-run <manifest>`, `lead-brief` | `son-brief`: `--lane --epoch`, `--max-bundle`, `--out`; `prefix`: `--stamp`, `--cwd`; `dry-run`: `--lane --worktree`, `--cwd`; `lead-brief`: `--stamp`, `--cwd`, `--task-file`, `--roster-json`, `--probe-json` | Son and lead briefs and the cached prompt prefix; starts no process. |
| `builder-audit.py` | none | `--base --owned` (required), `--repo`, `--claimed-sha`, `--status`, `--attempt` | Audit one builder's result against its owned files; read-only. |
| `flags_collect.py` | none | `--stamp --builder` (required), `--repo`, `--report-file` | Collect a builder report's FLAGS block into `flags.md`. |
| `walkthrough_fallback.py` | none | `--out`, `--url` (repeatable) (required), `--cwd` | Playwright fallback for the post-merge walkthrough. |
| `harness-lock.py` | `<action>` (acquire, release, check) | `--file --holder` (required), `--role` (head or son), `--ttl-sec`, `--lock-dir` | Lock a shared `.harness` record for one writer; only a head may lock. |

### 4.4 Parallel lanes (dpp)

`lanes.py` is the only writer of lane state. Global flags (before the subcommand): `--runs-dir`, `--cwd`, `--no-prs`.

| Subcommand | Arguments and flags | Purpose |
|---|---|---|
| `check <manifest>` | none | Overlap check on a lane manifest. |
| `lease <manifest>` | `--lane` (required), `--epoch` | Take a lane lease. |
| `branch-check <stamp>` | `--lanes` (required, comma-separated) | Branch-name collision check. |
| `son-command <manifest>` | `--lane --worktree` (required) | Print the son command line. |
| `plan` | `--from-checkin --draft` (required), `--outside`, `--full`, `--max`, `--stamp` | Admit lanes, add spend estimates, feasibility, `--full` selection. |
| `status <stamp>` | none | Lane status. |
| `sendback <stamp>` | `--lane --reason` (required) | Send a lane back. |
| `release <stamp>` | `--lane` (required), `--epoch` | Release a lane. |
| `fold <stamp>` | none | Fold lane results. |
| `stop-check <stamp>` | `--from-checkin` (required) | Whether fullauto may stop. |
| `report-check <report>` | `--lanes` (required) | Check the final report against lane ids. |
| `preflight <stamp>`, `budget <stamp>`, `loop <stamp>` | none | Pin the CLI version; budget report; fullauto loop cap. |
| `spawn <manifest>` | `--lane --worktree` (required), `--resume`, `--unsafe-no-sandbox` | Start a son under every cap. |
| `call <stamp>` | `--label` (required), `--timeout`, `--cost-source` (claude or none), `--prompt-file`, `--out`; command follows `--` | Any other model call behind the shared limit. |
| `heartbeat <stamp>` | `--lane` (required), `--turn`, `--status`, `--reason`, `--blocked-by` | Record a lane heartbeat or phase. |
| `merge-order <manifest>` | none | Print merge order. |
| `merge-plan <manifest>` | `--base` | Probe lanes against the merge target. |
| `merge-go <manifest>` | `--lane --head` (required), `--base` | Write `merge-go.md` for a verified head (head only). |
| `merge-target <stamp>` | `--set`, `--yes-default-branch` | Record the branch the run merges into. |
| `merge-go-step <stamp>` | `--step --head` (required), `--base` | Merge clearance for an autopilot step (head only). |
| `merge-done <manifest>` | `--lane` (required) | Mark a lane merged and restore `gc.auto`. |
| `gc-restore <stamp>` | none | Restore `gc.auto` after an aborted run. |

### 4.5 Maintenance and diagnostics

| Script | Subcommands and positionals | Key flags | Purpose |
|---|---|---|---|
| `doctor.py` | none | `--json` | Preflight checks for this machine (also `make doctor`). |
| `machine-prep.py` | `audit`, `plan`, `apply` | `--profile`, `--home`, `--claude-home`, `--tier`, `--days`, `--project` | Audit a machine against a blueprint profile; `apply` prunes plugins. |
| `usage-scan.py` | none | `--claude-home` (required), `--days` | Count Skill, Agent and MCP tool uses in recent transcripts; read-only. |
| `context-tax.py` | none | `--root`, `--budget`, `--max-description` | Measure always-loaded skill and agent metadata. |
| `settings_cache.py` | `[repo]` | `--get` | Parsed settings from `.harness/config.yaml` and the local frontmatter. |
| `bump-version.py` | `<version>` | `--root`, `--check` | Bump or verify the version in the four places it is recorded. |
| `changelog-join.py` | none | `--root`, `--version`, `--apply`, `--date` | Join `changelog.d/` fragments into the README changelog. |

### 4.6 Hook entry points (called by hooks, usable by hand)

| Script | Arguments | Purpose |
|---|---|---|
| `context-guard.py` | `--tool-calls --mb` (required); hook JSON on stdin | PostToolUse context guard. |
| `guard.py` | `--mode son\|merge` (required), `--cwd`; hook JSON on stdin | PreToolUse son deny list and merge gate. |
| `subagent_report.py` | `--event stop\|handback` (required); hook JSON on stdin | Report-section check. |
| `spawn_dry_run.py` | `--agent-dry-run`; hook JSON on stdin | Print the composed brief and command, start nothing. |
| `pr_payload.py` | `parse`, `view --body-out`, `body --body-file --receipt-file`, `payload [pairs...]` | Payload helpers for the PR-receipt hook. |

### 4.7 Other entry points

| Script | Arguments | Purpose |
|---|---|---|
| `sdk/dts2-run.py` | `<task>`; `--repo`, `--yes`, `--api-key-env`, `--second-opinion none\|codex\|gemini`, `--ship`, `--live-only` | Headless pipeline on the Agent SDK. |
| `evals/run.py` | `--fixture` (repeatable), `--baseline`, `--results-dir`, `--update-baseline` | Run the eval fixtures against the baseline. |

## 5. Makefile targets

Defined in the repository root `Makefile` (one level above the plugin directory).

| Target | What it runs |
|---|---|
| `make package` | Builds `dist/dts2-harness-<version>.zip` and `dist/dts2-marketplace-<version>.zip` with `git archive`. |
| `make test` | `cd plugins/dts2-harness && python3 -m unittest discover -s tests`. |
| `make check-version` | `bump-version.py <version> --check` against `plugin.json`. |
| `make doctor` | `python3 plugins/dts2-harness/scripts/doctor.py`. |
