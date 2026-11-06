# dts2-harness command inventory

Every command an agent or a user can run in this plugin, with its purpose, exact usage and what calls it. Built from the files themselves: `skills/*/SKILL.md` and the phase files beside them, `agents/*.md`, `hooks/hooks.json` and `hooks/*.sh`, the argparse definitions in `scripts/*.py` (and `scripts/lanes.py` for the lane commands), and the root `Makefile`. A test (`tests/test_inventory_complete.py`) fails when a `lanes.py` subcommand or a skill directory is missing from this page, so add a row in the same change that adds a command.

In examples, `$P` stands for `${CLAUDE_PLUGIN_ROOT}`, `<repo>` for a repo root, `<stamp>` for a run stamp and `<manifest>` for a lane manifest (`lanes.json`). Scripts print one JSON object on stdout unless noted. The "Since" column is `new` for a command added in 3.10.0 and `changed` for an existing command whose arguments or output changed; section 7 lists the changes.

For a shorter orientation (how to talk to the harness, which command when, the head, son and council flow) read `GUIDE.md` first. For one page of exact invocations per command (role, what it writes, flows, changelog locations) read `COMMANDS.md`.

Contents: 1 Skills, 2 Agents, 3 Hooks, 4 CLI scripts (4.1 state and progress, 4.2 detection and scaffolding, 4.3 roster, council and orchestration, 4.4 review and build gates, 4.5 parallel lanes, 4.6 maintenance, 4.7 hook entry points, 4.8 other entry points), 5 Library modules (5.1 lanes package, 5.2 templates), 6 Makefile targets and CI, 7 Changed in 3.10.0, 8 Settings keys, 9 Changed in 3.11.0, 10 Documentation.

## 1. Skills (slash commands)

Invoke as `/dts2:<name>`. Skills with `disable-model-invocation: true` in their frontmatter (`composio`, `dpp-full`, `fullauto`, `knowledge`, `machine-prep`, `model`, `onboard`, `sdk`) run only when the user types them. "Runs" lists the scripts the skill's own files name; "Hands off to" lists the skills it names.

| Command | Purpose | Usage and arguments | Runs | Hands off to |
|---|---|---|---|---|
| `/dts2:onboard` | Explain the harness (agents, skills, roster, tiers, lessons, headless runner) and recommend where to start. Explanation only, except an optional last step that adds hooks to the project after the user picks them. | no arguments | `delegate.py` (named in its text), `hooks-setup.py` | `autopilot`, `check-in`, `dpp`, `dpp-full`, `feature`, `find-skills`, `fullauto`, `model`, `ship` |
| `/dts2:composio` | Ask once whether the user has a Composio account, connect it (plugin by default, MCP or CLI on request), map the catalogue and connected accounts into `~/.dts2/composio-tools.json`, and offer to disable overlapping plugins, MCP servers and user skills (disable or archive with backup, never delete). | no arguments; drives `composio-setup.py status\|decide\|map\|overlap\|disable` | `composio-setup.py` | none |
| `/dts2:machine-prep` | Scan this computer's agent tooling, compare to the blueprint profile, prune by disabling, set up the slim startup. | no arguments; drives `machine-prep.py audit\|plan\|apply` | `env-detect.py`, `machine-prep.py` | none |
| `/dts2:setup` | Interview to an approved end state (`.harness/end-state.md`), then scaffold harness config in one repo, many repos or a workspace. A short router plus `phase-1-interview-a.md`, `phase-1-interview-b.md`, `phase-2-scaffold.md`. | `[path ...] [--scaffold-only]`; several paths means batch (scaffold only) | `scope-check.py`, `repo-size.py`, `app-type-detect.py`, `deploy-detect.py`, `clarity-score.py`, `roster.py`, `ensure-ignored.py`, `agent-memory.py`, `prod-scaffold.py` | `run`, `evolve` |
| `/dts2:run` | Plan, build, review and verify pipeline on a task in one repo or workspace; ends with a receipt. A short router plus `phase-0-size.md` to `phase-4-ship.md`, `modes.md` and `operations.md`. | `<task>`, `resume`, `section <#>`, `add secret NAME`, `review-pr <number>` | `scope-check.py`, `briefs.py`, `checks.py`, `council.py`, `delegate.py`, `roster.py`, `failover.py`, `plan-gate.py`, `plan_graph.py`, `builder-audit.py`, `flags_collect.py`, `findings.py`, `review_split.py`, `rollback_ref.py`, `walkthrough_fallback.py`, `companion-gate.py`, `skills-check.py`, `handoff-write.py`, `lanes.py` (`check`, `merge-plan`), `metrics.py`, `action-items.py`, `deploy-detect.py`, `ensure-ignored.py`, `agent-memory.py` | `setup`, `evolve`, `find-skills`, `action-items` |
| `/dts2:learn` | Consolidate reviewer and verifier findings into `.harness/lessons.md`; prune stale lessons (only after the user approves the drops). | no arguments, or `promote <L-NNN>` | `lessons.py`, `metrics.py`, `scope-check.py`, `action-items.py` | none |
| `/dts2:sdk` | Set up and run the pipeline headless with the Agent SDK (CI, cron, servers, WSL). | no arguments; runs `sdk/dts2-run.py` (section 4.8) | `sdk/dts2-run.py`, `roster.py` | none |
| `/dts2:evolve` | Change the harness itself in its source repo: edit, validate, test, bump versions, commit; push only on an explicit yes. | no arguments, or `deploy` to change the repo's deploy target | `deploy-detect.py` | none |
| `/dts2:action-items` | Show open Secrets, Decisions, Handoff, Deploy and Promotions items with age, owner and resolving command; mark done, add, assign. | no arguments (list), or the `done`, `add`, `assign` subcommands | `action-items.py`, `handoff-write.py` | `run`, `learn` |
| `/dts2:gtm` | Go-to-market in one pass: installs `marketing-skills` if missing, runs a deep-dive and applicable skills, ends with a readiness scorecard. | no arguments | `marketing-select.py`, `ensure-ignored.py` | none |
| `/dts2:ship` | Ship the current branch as a pull request: pre-check, repo checks, secret scan, verifier and reviewer, receipt, push, open PR; then sweep stale branches and PRs. Never merges. | `[base]`; base defaults to `dev` when it exists on the remote, else the default branch | `skills-check.py`, `handoff-write.py` | none |
| `/dts2:feature` | Add a feature to the roadmap: clarity score, interview when unclear, lead writes it into the end state, plan PR. Plans only; does not build. | `<description>` | `clarity-score.py`, `scope-check.py`, `action-items.py`, `handoff-write.py` | `setup`, `run`, `ship`, `autopilot` |
| `/dts2:autopilot` | Run harness steps unattended; a three-provider gate and a council replace the human checkpoints. One branch and PR per step. A short router plus `phase-0-preflight.md` to `phase-4-report.md` and `son-mode.md` (what a headless son reads first). | `<steps>` (section numbers like `3,4,7` or `3-5`, action-item ids, `feature "<text>"`, quoted tasks), `resume`, `status`, `--son <stamp>/<lane>` | `lanes.py`, `checks.py`, `council.py`, `briefs.py`, `roster.py`, `task-ledger.py`, `harness-lock.py`, `action-items.py` | `run`, `ship`, `check-in` |
| `/dts2:dpp` | Run several autopilot lanes in parallel as headless sons, one worktree each, under a head that plans, supervises and serialises merges. | `[dry-run] [--full] [resume]` | `lanes.py`, `plan_graph.py`, `briefs.py`, `checks.py`, `council.py`, `check-in.py`, `task-ledger.py`, `agent-memory.py` | `autopilot` (each son) |
| `/dts2:dpp-full` | `dpp` with `--full`: also fills lanes from a delegation scan and keeps dispatching without a new approval. | no arguments | none of its own | `dpp` |
| `/dts2:fullauto` | `dpp-full` with autopilot forced on, looping check-in until nothing is outstanding. | no arguments | `lanes.py` (`loop`, `stop-check`) | `dpp`, `dpp-full`, `check-in` |
| `/dts2:check-in` | Read-only progress against the approved end state: checklist, `N of M complete`, percent; `all` gathers check-in items from every session on the machine. | no arguments, or `all [--since 24h]` | `check-in.py`, `scope-check.py`, `action-items.py`, `fleet.py` (`checkins`, `broadcast`) | `action-items`, `autopilot`, `run`, `setup` |
| `/dts2:model` | Choose which agent provider fills the lead, advisory and sign-off seats; records `lead_provider`. Builders are unaffected. | no arguments | `roster.py`, `delegate.py`, `failover.py` | none |
| `/dts2:cooldown` | Pause an agent that hit a usage limit until its reset date, resume it, or list what is paused. | `set <agent> <date or duration> [reason]`, `clear <agent>`, `list` | `cooldowns.py` | none |
| `/dts2:fleet` | See every harness session on this computer, read status, logs and ledgers read-only, and broadcast a note, handoff, pause or knowledge finding to all of them. | `list [--all] [--json]`, `show <ref> [--json]`, `logs <ref> [-n 20]`, `broadcast --kind note\|handoff\|pause\|knowledge\|checkin --text T [--to ...] [--expires 24h] [--from-knowledge KEY]`, `status [<id>]`, `label <ref> <name>`, `prune [--days 14]` | `fleet.py` | none |
| `/dts2:incidents` | See and learn from agent incidents: list, live view, end-of-run brief, a reviewed debrief (root cause, lessons, promotion up the tier ladder). | `list [--open] [--json]`, `live`, `brief [--session S]`, `review`, `resolve <id> --root-cause T --how T`, `promote --tier harness\|knowledge <id>`, `lessons stats` | `incidents.py` | `learn`, `evolve` |
| `/dts2:knowledge` | Keep your own standing preferences, glossary terms and cross-project learnings in a private store that syncs across devices. | `setup`, `join`, `set <key> <value>`, `get <key>`, `find <text>`, `list`, `rm <key>`, `sync`, `status` | `knowledge.py` | none |
| `/dts2:find-skills` | Rescan the repo, audit every improvement option (skills, hooks, MCP servers, plugins, commands, subagents, permissions, CI), ask, and on a yes wire in the picks. | no arguments | `env-detect.py`, `repo-size.py`, `scope-check.py`, `skill-suggest.py`, `improve-scan.py`, `hooks-setup.py` | none |
| `/dts2:steer` | Stop running work and redirect it: the only command that stops a run. Finishes the current atomic step, dispatches nothing new, checkpoints a handoff, reviews open intake items, re-plans to the new direction, confirms in one short message, then resumes. | `<new direction>` (required; quote it when it has spaces) | `intake.py`, `handoff-write.py` | `run`, `autopilot` |
| `/dts2:ask-expert` | Decide the fate of one repo: goal questions with a clarity gate, a code read, what-you-said versus what-the-code-shows, overlap with your active repos, a three-provider expert panel (council and research when it stalls) and a one-page memo (keep, fold, template, archive, delete). A short router plus `phase-1-goal.md` to `phase-5-report.md`. | `[repo] ["what I'm unsure about"]` | `ask_expert.py` (`clarity`, `goal record`, `check-report`, `panel-tally`), `roster.py`, `ballot_dispatch.py`, `council.py` | `repo-sweep` |
| `/dts2:repo-sweep` | Quick ask-expert pass over every repo of an owner, oldest first, then one cleanup screen; archive is reversible, delete is one repo at a time after a verified backup and a typed name. | `[owner]` | `ask_expert.py` (`sweep add`, `sweep show`, `archive`, `backup`, `delete`), `gh` | `ask-expert` |
| `/dts2:pr-sweep` | Clear open and stale PRs in one pass with parallel workers: inventory, buckets A to H, merge green PRs with merge commits, rebase, triage red CI (fix, retry once, ignore non-required, flaky, escalate), close dead PRs with a comment, delete merged branches where permitted; `--optimise-ci` adds a separate CI-speed PR; `--run <stamp>` limits it to one autopilot run. A short router plus `phase-1-inventory.md` to `phase-4-optimise-ci.md`. | `[owner/repo] [--stale-days N] [--mine\|--author A\|--head-prefix P] [--optimise-ci] [--run <stamp>]` | `pr_sweep.py` (`inventory`, `classify`, `order`, `record`, `report`), `gh` | `autopilot` |

Source for each row: the `description` frontmatter and the usage line in the skill's own `SKILL.md`. The `run` skill also reads `skills/run/modes.md` for `add secret`, `review-pr` and the status lines.

## 2. Agents

Dispatched with the Agent tool as `subagent_type: dts2:<name>`.

| Agent | Role | Tools | Model, turn cap | Scripts it names |
|---|---|---|---|---|
| `dts2:lead` | Read-only planner: slices the end state into a DAG of tasks with exclusive file ownership, picks reviewer axes. Never writes code. | Read, Grep, Glob | opus, 25 | `briefs.py`, `contracts.py`, `delegate.py`, `repo-size.py`, `roster.py` |
| `dts2:builder` | Implements exactly one builder section inside its owned file set; does not review its own work. | Read, Write, Edit, Grep, Glob, Bash | sonnet, 60 | none |
| `dts2:fixer` | Fresh-context fixer for fix round 2 on the same failure: applies the one hypothesis the lead picked (escalation seat, `effort: high`). | Read, Write, Edit, Grep, Glob, Bash | opus, 40 | `delegate.py` |
| `dts2:reviewer` | Read-only reviewer: reviews a diff on one or all axes, returns severity-rated findings and a verdict. | Read, Grep, Glob | sonnet, 30 | `delegate.py`, `findings.py` |
| `dts2:verifier` | Read-only verifier: runs configured build, type, lint and test commands, checks for stubs, walks changed screens when asked. Evidence only. | Read, Grep, Glob, Bash (`disallowedTools`: Write, Edit, NotebookEdit) | opus, 40 | `checks.py` |
| `dts2:scout` | Read-only sizing scout: measures a repo, detects other harnesses and a marketing surface, recommends team tier, builder count and reviewer axes. | Read, Grep, Glob, Bash | haiku, 15 | `repo-size.py`, `deploy-detect.py`, `checks.py` |
| `dts2:auditor` | Read-only machine auditor: inventories installed agent tooling against a blueprint profile and proposes keep, disable and setup. | Read, Grep, Glob, Bash | sonnet, 20 | `env-detect.py`, `machine-prep.py` |
| `dts2:incident-reviewer` | Read-only incident reviewer: root cause with a short five-whys per open incident, isolated or trend, lessons, promotions and `harness:` lines. Never edits files. | Read, Grep, Glob, Bash | sonnet, 20 | `incidents.py` |

## 3. Hooks

Registered in `hooks/hooks.json`. Every hook script honours the `enabled` setting in `.claude/dts2-harness.local.md` (default true) and, except the guards that deny by design, never fails the session.

| Event (matcher) | Script | What it enforces | Calls | Since |
|---|---|---|---|---|
| SessionStart | `hooks/session-lessons.sh` | Puts the most recent harness lessons (`lessons_max`, default 5, only those whose `paths:` globs match changed files), open state items and open action items into context; after a compact prints a short resume pointer instead. | `scope-check.py --lessons` | changed |
| SessionStart | `hooks/session-cooldowns.sh` | Prints which agents are cooling down after a usage limit (do not call them) and which just came back. Silent when nothing is paused. | `cooldowns.py session-note` | new |
| SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd | `hooks/fleet-session.sh` | Registers the session in the shared fleet home and keeps its state and heartbeat (`working`, `idle`, `ended`); delivers unexpired broadcasts once per session (prompt, throttled tool check, stop for `handoff` and `pause`, later session start). Never blocks except the one `handoff`/`pause` keep-going at Stop. | `fleet.py` | new |
| Stop | `hooks/stop-checks.sh` | Refreshes `.harness/handoff/latest.md`, then a quick typecheck and lint on changed files with `node_modules/.bin/tsc` and `eslint` only (never npx; skipped when absent or the diff is unchanged), under one deadline 5 s below the hook timeout; a timed-out run saves a partial fingerprint. `.harness/checks.sh` is skipped in son mode. Warns on stderr; with `stop_checks_block: true` a red check blocks the stop once (never when `stop_hook_active`). | `handoff-write.py` | changed |
| PostToolUse (`Bash`, `gh pr create *`, `gh pr edit *` and `gh api *`) | `hooks/pr-receipt.sh` | Makes sure the PR body has a `## Change receipt` (receipt picked by the `dts2/<stamp>/` branch, else the newest stamped or `ship-<stamp>` run) and the repo PR template has the section; a `gh api .../pulls -X POST` counts as a PR create. Commits and pushes the template to the PR's own head branch only with `pr_receipt_template_push: true`, never in son mode. Never blocks. | `pr_payload.py` | changed |
| PostToolUse (`Bash\|Edit\|Write\|Agent`) | `hooks/context-guard.sh` | Stops a run on a context spike before the plan checkpoint, or when started in a member repo. Limits: `context_guard_tool_calls` (default 250), `context_guard_mb` (default 12); `context_guard` switches it off. | `context-guard.py` | changed |
| PostToolBatch | `hooks/context-guard.sh` | The same guard, once per batch of parallel tool calls; only the current run's `plan.md` counts as a plan checkpoint. `context_guard_stop: true` adds `continue:false` and a `stopReason` to the guard's output. | `context-guard.py` | new |
| PostToolUse (`SubagentHandback`) | `hooks/subagent-report.sh handback` | Blocks once per agent when a builder, reviewer or verifier report lacks the sections its contract names. | `subagent_report.py --event handback` | new |
| PreToolUse (`Bash`) | `hooks/merge-guard.sh` | Refuses a force-push, and a merge or push to a protected branch unless a lane's `merge-go.md` names the head and base commit. Denials are logged to `.harness/merge-guard.log`. | `guard.py --mode merge` | new |
| PreToolUse (`Bash`) | `hooks/policy-gate.sh` | Declarative policy for the head and every son (`templates/policy.json`): denies force-push, `--admin`, deploy CLIs, `gh secret`, `vercel env`, a bare `env`, `gh repo delete`; `gh pr merge` and a push to the default branch need the person's approval (a direct `gh pr merge <n> --squash --match-head-commit <sha>` also passes under the standing `merge_policy: auto-when-green` grant when the sha is the merge-go head and the live head, no `auto_merge_never_paths` file is touched and every required check is green; `--auto` is always refused); staging everything without a secret scanner is red when unattended. `policy_gate: false` switches it off. Denials are logged to `.harness/policy-gate.log`. | `policy_gate.py` | new |
| PreToolUse (`Bash`, `lanes.py spawn*--dry-run*`) | `hooks/spawn-dry-run.sh` | Prints the composed son brief and exact command, then refuses the call so nothing starts. | `spawn_dry_run.py` | new |
| PreToolUse (`Agent`) | `hooks/spawn-dry-run.sh` | With setting `spawn_dry_run: true`, denies the dispatch and prints the prompt; otherwise passes through. | `spawn_dry_run.py --agent-dry-run` | new |
| PreCompact (`auto\|manual`) | `hooks/pre-compact.sh` | Refreshes `.harness/handoff/latest.md` so the post-compact session can resume from it. | `handoff-write.py` | new |
| SubagentStop (`builder\|reviewer\|verifier`) | `hooks/subagent-report.sh stop` | Same report-section check as the handback hook, on the subagent's last message; skipped when `stop_hook_active`; a report starting `PARTIAL: hit turn cap at <step>` passes. | `subagent_report.py --event stop` | new |
| SubagentStop (`verifier`) | `hooks/subagent-stop.sh` | Blocks once when the newest run ledger lacks one of the five check lines (test, typecheck, lint, secret-scan, scope-check); skipped when `stop_hook_active` or no run exists. | `agent_events.py subagent-stop` | new |
| StopFailure | `hooks/stop-failure.sh` | Appends a Handoff action item naming the API error that ended the turn (rate limit, overload, auth, billing); deduplicated. | `agent_events.py stop-failure` | new |
| PermissionDenied | `hooks/permission-denied.sh` | Appends a Handoff action item naming the denied tool and reason; deduplicated. | `agent_events.py permission-denied` | new |
| SubagentStart, SubagentStop, PreToolUse (`Agent`), PostToolUse (`Edit\|Write\|MultiEdit\|Agent\|SubagentHandback`), Stop, SessionStart, SessionEnd | `hooks/agent-telemetry.sh <event>` | Records every agent start and stop in `.harness/agents.jsonl`, detects incidents (thin brief, no or partial or incomplete report, rework of another agent's file, hung spawn), injects up to 3 matching lessons into a starting subagent, queues one-line corrections for the lead, and writes the end-of-run brief and debrief. Never blocks. | `incidents.py hook <event>` | new |
| SessionEnd | `hooks/session-end.sh` | Releases only the lane leases this session took (reasons `logout`, `prompt_input_exit`, `other`), then refreshes the handoff. Lease expiry stays the guarantee. | `session_end.py`, `handoff-write.py` | new |
| UserPromptSubmit | `hooks/prompt-intake.sh` | Never blocks. Appends each prompt typed while the harness works to the intake queue (`.harness/intake.jsonl`), classifies it as fold, clarify or steer, and injects a one-line instruction for the agent. Timeout 10 s. Off with `intake: false` in `.claude/dts2-harness.local.md`. | `intake.py hook` | new |

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
| `loop_guard.py` | `check`, `record`, `park`, `sweep`, `notify` | `--repo`; `record`: `--progress` (required), `--signature`; `park`: `--id --reason` (required), `--blocker-pr` or `--blocker-item` or `--blocker-file`; `sweep`: `--release`; `notify`: `--reason` | Guard for the unattended fullauto loop: STOP file or `dts2:stop` PR label, pass and hour budget, progress ledger with stall verdict, parked items, one "dts2: needs you" issue. | `fullauto` | new |

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
| `hooks-setup.py` | `list`, `recommend`, `apply` | `--cwd`, `--home`, `apply`: `--ids` (required), `--scope`, `--dry-run` | List, recommend and add optional hooks (templates in `templates/hooks/`, not registered: `command-guard`, `auto-format`, `test-on-stop`, `notify`, `merge-on-green`, `db-guard`, `migration-check`) to project, local or user settings; merges only, never overwrites, backs up first. | `onboard`, `find-skills` | new |
| `unattended.py` | `diff`, `apply`, `status` | `--cwd`, `--home`, `--scope`, `apply`: `--dry-run` | Show and apply the unattended permission profile (`templates/settings.unattended.json`) to project, local or user settings; append-only, backs up first. `status` reports whether unattended mode is on. | `setup` | new |
| `composio-setup.py` | `status`, `decide`, `map`, `overlap`, `disable` | `--home`, `--cwd`, `decide`: `--account`, `--always-use`, `--connection`; `map`: `--from-json`, `--timeout`; `overlap`: `--all`, `--profile`; `disable`: `--ids`, `--dry-run` | Record the Composio decision, map toolkits and connected accounts to a user-level file, find overlapping plugins, MCP servers and skills, and disable or archive them with backup; never reads credentials, never deletes. | `composio`, `machine-prep` | new |
| `improve-scan.py` | none | `--cwd`, `--home` | Read-only audit of hooks, MCP servers, database tooling, plugins, slash commands, subagents, permission allowlist, CI and agent docs; ranked recommendations. MCP picks that a connected Composio toolkit covers (from `~/.dts2/composio-tools.json`) are dropped and listed under `info`. | `find-skills` | new |
| `marketing-select.py` | none | `--facts` | Ordered `marketing-skills` subset for the GTM pass. | `gtm` | |
| `skills-check.py` | `<repo>` | `--fix`, `--swap OLD=REF`, `--apply-update NAME=SHA`, `--no-upstream`, `--force-full`, `--son-root`, `--home`, `--plugin-root` | Pre-run check of harness version, marketplaces, companion and keep-list skills, with commit pins and proposal-only updates; the `skills` CLI is pinned (`SKILLS_CLI_VERSION`), a self-upgrade waits while a lane lease is live, and `--son-root` reports version skew. | `run`, `ship` | changed |
| `upgrade-check.py` | none | `--from-file` (required), `--plugin-json` | Compare the pre-upgrade version with the installed one. | `skills-check.py` (in-process); by hand | |
| `companion-gate.py` | `check`, `record` | `--repo`, `--skill` (required), `check`: `--base` | Run-count gates for two costly companion skills. | `run` | new |
| `env-detect.py` | none (no flags) | none | Report OS, WSL status, which Claude home is live and which agent CLIs are on PATH. Read-only. | `find-skills`, `machine-prep`; `auditor` agent | |

### 4.3 Roster, models and council

| Script | Subcommands and positionals | Key flags | Purpose | Called by | Since |
|---|---|---|---|---|---|
| `roster.py` | `detect`, `resolve`, `probe`, `model`, `command`, `classify` | `detect`: `--project`; `resolve`, `probe`: `--config`; `model`: `--agent --tier`; `command`: `--agent --role`, `--tier`, `--effort`, `--prompt-file`, `--workspace`, `--model`; `classify`: `--agent --role --exit-code`, `--axis`, `--usable` | Detect installed coding agents and resolve the roster into seats; `classify` treats exit 143 as a timeout so a council seat can be swapped. | `model`, `setup`, `run`, `sdk`, `autopilot`; `lead` agent | changed |
| `delegate.py` | none | `--agent --seat --complexity` (required), `--profile-dir`, `--budget`, `--lead-provider`, `--effort` | Resolve model, tier and effort for a dispatch seat (includes the `escalation` seat for the fixer). | `model`, `run`, `onboard`; `lead`, `fixer`, `reviewer` agents | changed |
| `failover.py` | none | `--current` (required), `--profile-dir`, `--exclude` | Pick the next lead provider on a usage or token limit. | `model`, `run` | |
| `cooldowns.py` | `set`, `clear`, `list`, `check`, `detect`, `expire`, `session-note` | `set`: `--until` or `--in`, `--reason`, `--by`, `--source`; `detect`: `--agent`, `--provider`, `--exit-code`, `--record`, `--by` | Per-account agent cooldowns in `~/.dts2/agent-status.json` (`DTS2_AGENT_STATUS` overrides): record a usage limit, read its reset date, skip the agent until then. `roster.py` probe and `classify`, `failover.py` and the SessionStart hook use it. | `cooldown`; `roster.py`, `failover.py`; session-cooldowns hook | new |
| `fleet.py` | `list`, `show`, `logs`, `broadcast`, `status`, `label`, `prune`, `checkins`, `checkin` | `list`: `--all --json`; `show`: `--json`; `logs`: `-n`; `broadcast`: `--kind --text --to --expires --from-knowledge`; `checkins`: `--since`; `checkin`: `--session --status`; `prune`: `--days` | Machine-wide session registry and broadcast inbox in `DTS2_FLEET_HOME` (else `DTS2_HOME/fleet`, else `~/.dts2/fleet`): one file per session, append-only `broadcasts.jsonl`, per-session delivery receipts. Read-only views never touch a running session. | `fleet`, `check-in` (all mode); fleet-session hook | new |
| `knowledge.py` | `setup`, `join`, `init`, `set`, `get`, `find`, `list`, `rm`, `sync`, `status`, `context` | `setup`: `--owner`, `--backend` (`git`, `folder`, `local`, `cloudflare`), `--remote`, `--path`, `--url`, `--force`; `join`: `--backend`, `--remote`, `--path`, `--url`; `init`: alias of `setup --backend git`; `set`: `--kind`, `--alias`, `--tag`, `--by`; `get`, `find`, `list`, `status`, `context`: `--json`; `find`, `list`: `--kind`; `context`: `--repo` | Personal preferences, glossary terms and learnings as Markdown files in `~/.dts2/knowledge` (`DTS2_KNOWLEDGE` overrides), a private git repo, a Cloudflare Worker + D1 (`--url`; token only from `DTS2_KNOWLEDGE_TOKEN`), a drive-synced folder or local only (device profile in `~/.dts2/knowledge.json`). Rejects secrets. Read only on user request and by `setup`. | `knowledge`, `setup` | new |
| `knowledge_cloudflare.py` | `ping`, `list`, `pull <store>` (run directly; `--url` is required) | `--url`; token from env `DTS2_KNOWLEDGE_TOKEN` | Client for the Cloudflare Worker + D1 knowledge backend; `knowledge.py sync` delegates to it. Never writes the token to disk. | `knowledge.py` | new |
| `ask_expert.py` | `clarity`, `goal record`, `check-report`, `scorecard`, `sweep add`, `sweep show`, `panel-tally`, `archive`, `backup`, `delete` | `clarity`: `--answers --asked --threshold`; `goal record`: `--repo --answers`; `scorecard`: `--report --goal`; `sweep add`: `--ledger --repo --verdict --confidence --reason --score --salvage --report`; `panel-tally`: `--plans SEAT=FILE... --votes SEAT=FILE... --blind-key FILE --record DIR --round N`; `archive`, `backup`: `--repo OWNER/NAME`, `--dest`; `delete`: `--repo --confirm --bundle` | Repo decision support: slot-scored goal clarity (threshold 95), strict memo checker, nine-factor weighted scorecard, sweep ledger sorted by score, and archive, backup (verified `git bundle`) and delete with guards (exact typed name plus verified bundle, one repo per call). | `ask-expert`, `repo-sweep` | new |
| `pr_sweep.py` | `inventory`, `classify`, `order`, `record`, `report` | `inventory`: `--repo OWNER/NAME --stale-days --head-prefix --author --out DIR`; `classify`, `order`: `--inventory FILE --now ISO`; `record`: `--dir --pr --bucket --action --sha --reason --ci --worker --verified-by`; `report`: `--dir` | PR sweep support: REST-only `gh api` inventory with required checks per base branch, pure bucket classifier (green, needs rebase, CI red, stacked, draft, pending, plus stale flag, overlaps, shared-file hits and superseded or needs-me candidates), merge waves (stack bases first, shared files one at a time), run ledger and report. | `pr-sweep` | new |
| `agent_events.py` | `subagent-stop`, `stop-failure`, `permission-denied` | event name; hook JSON on stdin | Hook handlers: verifier stop gate on the N3 check lines; StopFailure and PermissionDenied append a Handoff action item. | `hooks/subagent-stop.sh`, `stop-failure.sh`, `permission-denied.sh` | new |
| `incidents.py` | `hook <event>`, `list`, `live`, `brief`, `resolve`, `lessons stats`, `promote`, `review-input`; helpers in `incidents_detect.py` and `incidents_lessons.py` | `list`: `--open`, `--json`; `brief`: `--session`; `resolve`: `--root-cause`, `--how`; `promote`: `--tier harness\|knowledge`, `--text` | Agent telemetry, incident capture, lesson injection with helpful/harmful counters, and the tier ledgers (project, harness, knowledge store). No model calls. | `hooks/agent-telemetry.sh`; `agent_events.py` | new |
| `seat_swap.py` | `swap`, `identical` | `swap`: `--seats --failed`, `--ledger`, `--step`, `--reason`; `identical`: `--votes-dir --ledger --step --prev --curr` | Council seat substitution and identical-findings ledger note. | `council.py swap` and `identical` (in-process) | new |
| `council.py` | `eligible`, `dossier`, `tally <ballots...>`, `check-decision <decision>`, `route`, `blind`, `wrap <file\|->`, `ledger`, `seats`, `swap`, `identical`, `next-round` | `eligible`: `--votes-dir`; `dossier`: `--votes-dir --out`; `check-decision`: `--tally --entries`, `--ledger`, `--head`, `--allow-research` (ask-expert only: accepts `DECISION: RESEARCH` with a non-empty `## Research brief`); `route`: `--ledger`, `--head`, `--votes`, `--decision` (APPROVE, FIX, STRIKE), `--allow-research` (returns action `research`); `blind`: `--proposals --out --voters --seed`, `--ledger`, `--authors`; `wrap`: `--source`, `--max-chars`; `ledger`: `--ballots-dir --tally --decision --step --stamp --out`; `seats`: `--usable`, `--config`, `--failed`; `swap`: `--seats --failed`, `--ledger`, `--step`, `--reason`; `identical`: `--votes-dir --ledger --step --prev --curr`; `next-round`: `--votes-dir --step --kind`, `--retry`, `--revote` | Autopilot council: dossier, ballot tally, decision check, routing of red checks to a fix round, blinding, seat substitution, ballot instance ids (`<step>+<attempt>`; dispatch errors, malformed ballots and 429 are retried, not voted) and the untrusted-content fence. | `run`, `dpp`, `autopilot` | changed |
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
| `son-command <manifest>` | `--lane --worktree` (required), `--wrap` | Print the son command line (on the `son_model` setting); `--wrap` adds the session id, stream-json and `son.json`. | `lanes.py spawn` (in-process) | |
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
| `fold <stamp>` | `--apply <group> --pr <n>` | Fold lane results into named groups, one PR each; `--apply` records `superseded_by` and the new PR on each original (G-79). Head only. | `dpp` | changed |
| `fold-close <stamp>` | none | Close each superseded original with a link comment to the new PR; checks the PR state first and journals each close (G-79). Head only. | `dpp`, `autopilot` | new |
| `fold-done <stamp>` | `--group` (required), `--pr` | Record that a fold group's PR is shipped. | none yet | new |
| `stop-check <stamp>` | `--from-checkin` (required), `--base` | Whether fullauto may stop; items tied to a ledgered blocked PR do not count; `--base` reads the end state from the fetched `origin/<base>`. | `fullauto` | changed |
| `approve-lane <stamp>` | `--lane` (required) | Record the user's yes for one lane (`dpp_full_ask_each_lane`); `lease` refuses a lane without it. Head only. | `dpp` | new |
| `override <lane>` | `--reason` (required) | The owner's override of a lane rule, logged to `state.md`; refused in a son, a vote or the council, and without the human approval channel. | none yet | new |
| `mailbox <op> <stamp>` | `op` (ask, need-human, answer, check, wait, park, merge-go-check, rules, request, decide); `--lane` (required), `--id`, `--text`, `--reason`, `--session-id`, `--point`, `--files`, `--outcome`, `--epoch`, `--worktree` | The head/son mailbox: versioned question, answer, need-human, send-back and merge-go messages with a deadline (`mailbox_wait_min`) and a park on expiry; the son's merge-go HEAD check; rule re-read digests; the out-of-lane ladder. | `autopilot --son`, `dpp` | new |
| `branch-check <stamp>` | `--lanes` (required, comma-separated) | Branch-name collision check. | none (internal) | |
| `preflight <stamp>` | none | Pin the CLI version and test the real son launch. | `dpp` | new |
| `budget <stamp>` | none | Budget report. | `dpp` | new |
| `loop <stamp>` | none | Fullauto loop cap. | `fullauto` | new |
| `call <stamp>` | `--label` (required), `--timeout`, `--cost-source` (claude or none), `--prompt-file`, `--out`; command follows `--` | Any other model call behind the shared limit; the command runs with a scrubbed env (`provider_env`: no `GH_TOKEN`, cloud keys or, for a non-Claude command, Anthropic credentials). | `autopilot` | new |
| `publish <stamp>` | `--lane` (required), `--branch`, `--base`, `--title`, `--body` | The head pushes a finished lane branch and opens or adopts its PR (`head_publish.publish_lane`); a diff that touches protected files parks the lane and pushes nothing. Refused for a son, a voter or a council seat (env marker or `DTS2_ROLE`), and denied in a son's Bash (`lanes.py publish`). | `dpp`, `autopilot` (head only) | new |
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
| `fix-attempt <stamp>` | `--lane --reason` (required) | Count a post-merge fix; past `post_merge_fix_attempts` open one revert PR (or park with the revert action item) (G-78). Head only. | `autopilot`, `dpp` | new |
| `base-health <stamp>` | none | Is the fetched `origin/<base>` green? Records `base-health.json`; `merge-go` refuses while it is red or the base moved (G-78). Head only. | `autopilot`, `dpp` | new |
| `merge-mutex <stamp>` | `--lane --op acquire\|release\|status` (required) | The repo-wide merge mutex, held from the rebase to the post-merge PASS; `merge-go` refuses another lane while it is held (G-78). Head only. | `autopilot`, `dpp` | new |
| `walkthrough-failed <stamp>` | `--lane --reason` (required) | Record a failed post-merge walkthrough and file one revert action item. | none yet | new |
| `report <stamp>` | `--repo-url` | The run as a markdown table plus run-wide sections: refusals, overrides, merge order and rebases, total spend, check-in delta, per-son CI result, merge commit and out-of-lane requests. | none yet | changed |
| `report-check <report>` | `--lanes` (required), `--stamp` | Check the final report against lane ids; with `--stamp` also cross-check the son run records (unlisted lanes, PRs the report never names). | `dpp` | |

"None yet" means no skill or hook text calls the command in 3.10.0: the head can run it by hand, and the lifecycle commands are the API a later skill change is meant to wire in.

### 4.6 Maintenance and diagnostics

| Script | Subcommands and positionals | Key flags | Purpose | Called by | Since |
|---|---|---|---|---|---|
| `doctor.py` | none | `--json` | Preflight checks for this machine: python, git, claude, sandbox, bwrap, socat, auth method (named, never the value), platform. On native Windows the platform row warns that dpp parks (`windows-native`); exit codes by runtime are in `docs/RUNTIMES.md`. | `make doctor` | changed |
| `plugin_options.py` | `show`, `get KEY [--default V]`, `data-dir` | none | Per-user knobs from `CLAUDE_PLUGIN_OPTION_<KEY>` (plugin `userConfig`) and the non-repo cache directory `CLAUDE_PLUGIN_DATA`; per-repo settings stay in `.claude`. | none yet | new |
| `receipts_sign.py` | `append JOURNAL BODY`, `verify JOURNAL`, `sign FILE`, `check FILE SIG` | none | Hash-chained journal and HMAC-signed receipts (hashlib, hmac); the key file is named by `DTS2_PR_RECEIPT_KEY_FILE`, which sons never receive. | none yet | new |
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
| `pr_payload.py` | `parse`, `view --body-out`, `body --body-file --receipt-file`, `decisions --ledger`, `payload [pairs...]` | Payload helpers for the PR-receipt hook; `decisions` prints the "Decisions and declined findings" PR section from the ledger. | pr-receipt hook, ship | changed |
| `intake.py` | `add [--text T] [--source hook\|cli]`; `list [--status S] [--json]`; `resolve <id> --as fold\|clarify\|steer\|done [--note N]`; `answer <id> --text T`; `status`; `hook`; global `--root DIR`, `--threshold N` (default 60), `--budget N` (default 2) | | Prompt intake queue: records each prompt typed while the harness works in `.harness/intake.jsonl`, scores its clarity (0-100), classifies it as fold, clarify or steer, and renders `.harness/intake.md`. `hook` is the `UserPromptSubmit` entry point and never blocks a prompt. | prompt-intake hook (`hook`); `/dts2:steer` and the agent (`list`, `resolve`, `answer`) | new |

### 4.8 Other entry points

| Script | Arguments | Purpose | Called by | Since |
|---|---|---|---|---|
| `plan_graph.py` | `analyse <manifest>`, `merge-order <manifest> --runs-dir D`, `brief <manifest> --lane L`; global `--cwd` | Plan graph for a lane manifest: `provides`/`consumes`/`stubbed_on` contracts, prefix and glob owners, package-root areas, cycle check, critical path. `analyse` prints the report, `merge-order` records the provider-first order, `brief` prints the six-section lane brief. Read-only except `merge-order`. | `run`, `dpp`; `lanes.py check`, `lease`, `plan` (in-process) | new |
| `protected.py` | `<repo> paths`, `<repo> check [names...]` | | Protected paths a son's diff must not touch (git common dir config/info/hooks, `.gitattributes`, workflows, checks script, CODEOWNERS, `hooks/`, head-only `.harness` records, `merge-go.md`); a touching diff parks as a Decisions item. | `head_publish.py`; `dpp` | new |
| `policy_gate.py` | `--cwd`; hook JSON on stdin | | Declarative policy gate: evaluates `templates/policy.json` (deny, require-approval, scanner-required) after unwrapping `bash -c`, `eval`, `env`, `command`, `sudo`, `npx`, `git -C` and chains; approvals come from `approvals.py` (kinds include `merge` per PR and the standing `merge_policy`). | policy-gate hook | new |
| `approvals.py` | `--repo`; `check <kind> <key> [--session]`, `path` | | Human-only approval channel: `dts2_approvals` in `.claude/settings.local.json`, which the model cannot write; logs the asker as `human` or `agent:<session>`. | `head_publish.py`; `dpp`, `autopilot` | new |
| `head_publish.py` | `--repo`; `publish --lane --branch --base --title [--body]`, `merge <pr> [--verifier-ok --default-branch --deploys-production]`, `bootstrap --stamp --lane --worktree` | | The head pushes and opens one PR per lane, merges when the preconditions hold (checks reported and green, protection or queue, a per-PR yes for a production deploy) and bootstraps each lane (install once, sanitized `son.env`, missing secrets filed). Intended `lanes.py publish`. | `dpp`, `autopilot` (head only) | new |
| `provider_report.py` | `footer`, `check <file\|->` | | Provider-neutral brief footer and validator for the fenced JSON report every non-Claude seat ends with. | `run`, `autopilot` | new |
| `ballot_dispatch.py` | `dispatch --seat --model --prompt-file --out-dir [--provider] [-- argv]` | | Runs one council seat through the shared call limit and writes the ballot with its `.dispatch.json` record (argv, model, session id, sha256); Claude seats use `--json-schema` and `--restricted`. | `autopilot` council | new |
| `sdk/dts2-run.py` | `<task>`; `--repo`, `--yes`, `--api-key-env`, `--second-opinion none\|codex\|gemini`, `--ship`, `--live-only` | Headless pipeline on the Agent SDK (`claude-agent-sdk` pinned in `sdk/requirements.txt`): per-role tools (only the verifier has Bash), `setting_sources=['user']`, turn and budget caps, a secret scan before `git add -A`, no Anthropic key in a second-opinion CLI's env. | `sdk` | |
| `evals/run.py` | `--fixture` (repeatable), `--baseline`, `--results-dir`, `--update-baseline`, `--runs`, `--arm-b-env` | Run the smoke-eval fixtures against the baseline; with `--arm-b-env` run k >= 5 alternating A/B runs and report median, range, pass^k and a verdict. | by hand | changed |

## 5. Library modules (no command line)

Imported by the scripts above; none is a CLI. Responsibilities are in `ARCHITECTURE.md`.

`_load.py`, `contracts.py`, `eval_stats.py` (A/B run statistics for `evals/run.py`: median, range, pass^k, verdict), `harness_skew.py` (live-lease read, son-versus-head plugin version skew (also checked by `supervisor.spawn_refusal` before every son start; `DTS2_SON_PLUGIN_ROOT` points it at another son plugin dir), marketplace repo from `plugin.json`), `mdparse.py`, `miniyaml.py`, `model_call.py`, `ownership_audit.py`, `prep-tiers.py` (helper for `machine-prep.py`), `proc.py` (also the son lifecycle: `wrap_son`, `son.json`, `exit.json`, SIGINT-then-SIGKILL), `profiles.py`, `skill_pins.py`, `son_launch.py` (also `provider_env`, `allowed_tools`, `auth_problem`, `init_plugin_errors`), `son_stream.py` (stream-json heartbeat, `detect_stuck`, `api_retry` exhaustion), `state_ids.py`, and the modules of `scripts/lanes/` (`amend`, `common`, `conflicts`, `gitrefs`, `integration`, `journal`, `leases`, `merge`, `mergecomp`, `mergeplan`, `mergeresume`, `phases`, `planner`, `reconcile`, `records`, `runend`, `runrecord`, `runstate`, `shutdown`, `supervisor`, `waiter`).

### 5.1 `scripts/lanes/` modules

The package behind `lanes.py` (dependency order and flows are in `ARCHITECTURE.md`). Library only: none has a command line.

| Module | Holds | Since |
|---|---|---|
| `lanes/__init__.py` | Package marker; re-exports the public names `lanes.py` imports. | 3.10.0 |
| `lanes/amend.py` | `amend`: change one lane of a running manifest, re-check, bump the epoch, rewrite `brief.md`. | 3.10.0 |
| `lanes/audit.py` | `lane_audit`: did the lane's branch change only files its manifest entry owns (`git diff --name-only` between base and head). | 3.11.0 |
| `lanes/common.py` | Constants (phase names, `HEARTBEAT_PHASES`, `COST_SOURCES`, `LANE_SECTIONS`), `LaneError`, `load_manifest`. | 3.10.0 |
| `lanes/conflicts.py` | Overlap detection between lanes (file, schema, id, dependency, area, scope) and the open-PR and active-run sources. | 3.10.0 |
| `lanes/gitrefs.py` | Lane branch names (`dts2/<stamp>/lane-<id>`) and the collision check against existing refs. | 3.10.0 |
| `lanes/integration.py` | Routes lockfiles, migrations, route tables, barrels and `lanes.shared_files` globs to a final integration lane; caps a PR at 5 tasks. | 3.10.0 |
| `lanes/journal.py` | `merge-journal.jsonl`: grants, merges, fold plans, shipped fold groups, failed walkthroughs, the revert action item, the post-merge fix cap and revert PR (`fix-attempt`), the supersede close (`fold-close`). | changed |
| `lanes/leases.py` | Lane leases: epoch fence, expiry, `renew_lease`, the item hold, and the overlap check plus lease write under one admission lock. | changed |
| `lanes/mailbox.py` | The head/son mailbox: versioned question, answer, need-human and out-of-lane request files, send-backs, `merge-go.json`, deadlines with a defined park transition, rule-file digests (`lanes.py mailbox`). | 3.11.0 |
| `lanes/mergecomp.py` | Base-health record and merge gate, the repo-wide merge mutex, integration routing records shown by `status` and `report`. | 3.11.0 |
| `lanes/merge.py` | Merge order, merge target, `merge-go` grants and `merge-done`; `merge-go-step` applies the same base-health and mutex refusal as `merge-go`. | changed |
| `lanes/mergeplan.py` | Merge queue or serial rebase-test-merge plan with the `git merge-tree --write-tree` probe. | 3.10.0 |
| `lanes/mergeresume.py` | Settle a merge a dead head left half done, by asking GitHub. | 3.10.0 |
| `lanes/phases.py` | `transition`, the one writer of a lane's phase, with its `LEGAL` table. | 3.10.0 |
| `lanes/planner.py` | The son command line, admission, spend estimates and the `plan` command (frozen-scope filter before the cap). | changed |
| `lanes/policy.py` | Scope and approval policy around `plan`: the owner override, ask-before-each-lane, frozen fullauto scope, end state from `origin/<base>`. | 3.11.0 |
| `lanes/reconcile.py` | Ask GitHub before creating, merging or resuming; orphan handling; deterministic mappings. | 3.10.0 |
| `lanes/records.py` | Locked reads and writes of one JSON object through the state port, the model-call ledger. | 3.10.0 |
| `lanes/runend.py` | Run metrics at the end of a run and the run report view (refusals, overrides, merge order, spend, per-son lines). | changed |
| `lanes/runrecord.py` | The typed `run.json` (`RunRecord`) and `builders.jsonl` rows. | 3.10.0 |
| `lanes/runstate.py` | Status and stall marks, send-backs, `fold` groups, `stop-check`, `report-check`, the budget counter and spend ledger. | changed |
| `lanes/shutdown.py` | Graceful end of a run: park running lanes, stop son process groups, close leases. | 3.10.0 |
| `lanes/supervisor.py` | `preflight`, `spawn` and the son lifecycle, `model_call`, `loop`, `gc_restore`; `spawn_refusal` checks plugin version skew. | changed |
| `lanes/waiter.py` | `lanes.py wait`: return on a phase change or a son's `exit.json` (inotify, else sleep-backoff). | 3.11.0 |

### 5.2 Templates

Files under `templates/`, copied or filled by setup and the scripts named here.

| Template | What it is | Since |
|---|---|---|
| `templates/RUNBOOK.md` | Production runbook skeleton written by `prod-scaffold.py`. | 3.10.0 |
| `templates/action-items.md` | Empty `.harness/action-items.md`. | 3.10.0 |
| `templates/ci.yml` | CI workflow the setup skill offers a repo. | 3.10.0 |
| `templates/config-supervisor.yaml` | Run caps and supervisor settings (`budget`, `supervisor`, `sandbox`, `merge`, `lanes`, `walkthrough`) to merge into `.harness/config.yaml`. | changed |
| `templates/dependabot.yml` | Dependency-update config the setup skill offers. | 3.10.0 |
| `templates/discipline.md` | The rules copy a repo gets at setup. | 3.10.0 |
| `templates/dts2-harness.local.md` | Per-repo hook and run settings (see section 8). | changed |
| `templates/end-state.md` | Empty `.harness/end-state.md`. | 3.10.0 |
| `templates/handoff-latest.md` | Layout of `handoff/latest.md` written by `handoff-write.py`. | 3.10.0 |
| `templates/harness-lessons.md` | Empty `.harness/lessons.md`. | 3.10.0 |
| `templates/keep.yaml` | Keep list for `machine-prep` and `skills-check.py`. | 3.10.0 |
| `templates/knowledge-cloudflare/` | Worker + D1 backend for the personal knowledge store (`wrangler.toml`, `schema.sql`, `src/index.ts`, `README.md`); the user deploys it with wrangler. | new |
| `templates/ops/` | Production runbooks (`backups.md`, `credential-handoff.md`, `monitoring.md`, `release.md`, `rollback.md`) copied by `prod-scaffold.py`. | 3.10.0 |
| `templates/policy.json` | Declarative deny and require-approval rules read by `policy_gate.py` (`hooks/policy-gate.sh`). | 3.11.0 |
| `templates/pr-template.md` | PR body with the change receipt and the "Decisions and declined findings" section. | changed |
| `templates/receipt.md` | Change receipt skeleton filled by the ship step. | 3.10.0 |
| `templates/renovate.json` | Renovate config the setup skill offers. | 3.10.0 |
| `templates/son-brief.md` | The ~4 KB `brief.md` a son reads first, filled by `briefs.py son-brief`. | 3.10.0 |
| `templates/state.md` | Empty `.harness/state.md`. | 3.10.0 |

Tests for the knowledge store: `tests/test_knowledge.py` (CLI, backends, profile) and `tests/test_knowledge_cloudflare.py` (Cloudflare client with a fake server; no network). Run with `python3 -m unittest discover -s tests -p <file>`.

| Test file | Covers | Since |
|---|---|---|
| `tests/test_knowledge_cloudflare.py` | `knowledge_cloudflare.py`: entry format, pull and push by newer `updated`, token handling | new |

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
| Agent | `dts2:fixer` (the `escalation` seat in `delegate.py`) | AA-4 |

### 7.2 Changed commands

| Command | What changed | Source |
|---|---|---|
| `lanes.py check`, `lease`, `plan` | Run the plan-graph checks; owners may be `dir/` prefixes or globs; routing of lockfiles, migrations, route tables, barrels and `lanes.shared_files` to a final integration lane (a PR bundles at most 5 tasks); `lease` and `plan` fail closed without `gh`; leases carry `expires_at` and `ttl_s`, take the check and the write under one admission lock, and record `session_id`; `plan` adds spend estimates and a `graph` block | G-20, G-16, G-25, B6, G-26 to G-28, Q-22 |
| `lanes.py release`, `sendback`, `status`, `fold` | `release` refuses a stale `--epoch`; the epoch is mandatory in the state port; send-backs are counted atomically; `status` shows heartbeat and stalls; `fold` names each group | G-11, N2, G-15 |
| `lanes/mergecomp.py` | Base-health record and merge gate, repo-wide merge mutex, integration routing records (refusal, reason, alternative, override) printed by `status` and `report` (G-78, G-80) | G-78, G-80 |
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

## 8. Settings keys

Keys of `templates/dts2-harness.local.md`, copied to `<repo>/.claude/dts2-harness.local.md` (restart Claude Code after editing). Hooks read them through `hooks/lib-settings.sh`, scripts through `lanes.read_setting`. Run caps (`budget`, `supervisor`, `sandbox`, `merge`, `lanes`, `walkthrough`) live in `.harness/config.yaml` (`templates/config-supervisor.yaml`). Human approvals are not a setting: they are the `dts2_approvals` key in `.claude/settings.local.json`, read by `approvals.py`.

| Key | Default | Effect |
|---|---|---|
| `enabled` | `true` | Master switch for every hook. |
| `stop_checks` | `true` | Stop hook runs quick typecheck and lint. |
| `stop_checks_block` | `false` | A red check blocks the stop once. |
| `lessons_inject` | `true` | SessionStart loads lessons. |
| `lessons_max` | `5` | Most lessons loaded. |
| `pr_receipt_template_push` | `false` | Receipt hook commits and pushes the PR template (never in a son). |
| `auto_scale` | `true` | `run` picks tier S/M/L/XL itself. |
| `max_builders` | `4` | Builders in parallel. |
| `max_reviewers` | `4` | Reviewers in parallel. |
| `continuous_dispatch` | `true` | Keep `max_builders` in flight; park stalled builders. |
| `builder_timeout_min` | `20` | Minutes without a builder report before it is parked. |
| `son_permission_mode` | `dontAsk` | `claude -p` permission mode for sons (`bypassPermissions` is refused). |
| `mailbox_wait_min` | `30` | Minutes a son waits for the head before it parks `mailbox-timeout`. |
| `dpp_full_ask_each_lane` | `true` | `dpp-full` outside autopilot asks before each new lane (`approve-lane`). |
| `fullauto_freeze_scope` | `true` | `fullauto` freezes the approved item set at its first plan. |
| `post_merge_fix_attempts` | `2` | Post-merge fixes per lane before a revert PR opens. |
| `son_model` | `opus` | Model every dpp son runs on. |
| `use_worktrees` | `auto` | `auto`, `always` or `never` for builder worktrees. |
| `second_opinion` | `none` | `none`, `codex` or `gemini` for the sdk runner. |
| `profile` | `blueprint` | `machine-prep` profile name or path. |
| `end_state_threshold` | `80` | End-state clarity score needed. |
| `auto_learn` | `true` | Run `learn` after the ship checkpoint. |
| `context_guard` | `true` | Context guard hook on or off. |
| `context_guard_tool_calls` | `250` | Tool calls before the guard fires. |
| `context_guard_mb` | `12` | Transcript MB before the guard fires. |
| `context_guard_stop` | `false` | The guard also ends the turn (`continue:false`). |
| `policy_gate` | `true` | Declarative policy hook (`templates/policy.json`) on or off. |
| `max_execution_effort` | `high` | Cap on builder effort. |
| `delegation_strict` | `true` | Block ship if a builder ran a frontier model. |
| `lead_provider` | `claude` | Agent for the lead, advisory and sign-off seats. |

## 9. Changed in 3.11.0

Sources: `CHANGELOG.md` (3.11.0) and `git log --oneline 6a74faa..HEAD -- plugins/dts2-harness` (the 3.10.0 release is the base). Ids such as G-70 are the batch ids used in the changelog.

### 9.1 New commands and files

| What | Commands and files | Source |
|---|---|---|
| Head policy gate | `hooks/policy-gate.sh`, `policy_gate.py`, `templates/policy.json`, setting `policy_gate` | G-70 |
| Son containment | `protected.py`, `approvals.py`, `head_publish.py` (`publish`, `merge`, `bootstrap`), `provider_report.py`, `ballot_dispatch.py`; `lanes.py publish` | G-60 to G-69 |
| Son lifecycle | `son_stream.py`, `lanes/waiter.py`; `lanes.py wait`, `gc`, `reconcile` mappings | G-52 to G-58 |
| Mailbox and scope policy | `lanes/mailbox.py`, `lanes/policy.py`; `lanes.py mailbox`, `override`, `approve-lane`; settings `mailbox_wait_min`, `dpp_full_ask_each_lane`, `fullauto_freeze_scope` | G-43 to G-51 |
| Merge safety | `lanes/mergecomp.py`; `lanes.py base-health`, `merge-mutex`, `fix-attempt`, `fold-close`; setting `post_merge_fix_attempts` | G-78 to G-80 |
| Agent gates | `hooks/subagent-stop.sh`, `hooks/stop-failure.sh`, `hooks/permission-denied.sh`, `agent_events.py` | G-72 to G-74 |
| Eval and skills | `eval_stats.py` (A/B mode of `evals/run.py`), `harness_skew.py`, pinned `skills` CLI | G-75 to G-77 |
| Reports and receipts | `lanes.py report` run-wide sections, `receipts_sign.py`, `plugin_options.py`, `OTEL_` env allowlist entry | G-82 to G-87 |
| Hooks | `python3 -I` in every hook, `lib-settings.sh` parity with `lanes.read_setting` | G-30 to G-40 |

### 9.2 Changed commands

| Command | What changed | Source |
|---|---|---|
| `lanes.py merge-go-step` | Same base-health and merge-mutex refusal as `merge-go`; a `revert-<lane>` step acts for the mutex holder | review fixes |
| `lanes.py plan`, `lease` | Frozen-scope filter before the cap; a lease records its check-in item and refuses one another live lease holds | G-47, G-50 |
| `lanes.py heartbeat` | The no-phase heartbeat checks the epoch under the status lock and renews nothing when stale | review G |
| `lanes.py status`, `report` | Routing records, CI result, merge commit, out-of-lane requests, run-wide sections | G-80, G-82 |
| `lanes.py spawn`, `preflight` | Non-bare spawn checks `auth_problem`, `init_plugin_errors`, a push dry-run under the head env and plugin version skew | G-60, G-76 |
| `council.py next-round`, `tally` | Instance ids `<step>+<attempt>` count up across rounds; a ballot needs a valid `.dispatch.json` | G-68, G-72 |
| `receipts_sign.py` | Fails closed when `DTS2_PR_RECEIPT_KEY_FILE` is set but unreadable or empty | G-87 |
| `evals/run.py` | `--runs` and `--arm-b-env` A/B mode with median, range, pass^k and a verdict | G-75 |
| `skills-check.py` | Pinned `skills` CLI; no self-upgrade while a lease is live; `--son-root` skew report; no org string | G-76, G-77 |
| `doctor.py` | Reports bwrap, socat, auth method and platform; native Windows warns | G-85 |
| Hooks `stop-checks.sh`, `pr-receipt.sh`, `context-guard.sh`, `session-lessons.sh` | `python3 -I`, one shared deadline, branch-to-stamp receipt, current-run plan check, lessons inside the untrusted fence | G-30 to G-37, G-69 |

## 10. Documentation

Pages under `docs/` and the plugin root that an agent reads. None is a command.

| Page | What it holds | Since |
|---|---|---|
| `docs/COMMANDS.md` | Command reference for agents: every `lanes.py` subcommand, script, skill, agent and hook with role, exact invocation and what it writes; six copy-paste flows; where the changelogs live. | 3.11.0 |
| `docs/GUIDE.md` | Agent guide: how to talk to the harness, which command when, head, son and council flow, release digests. | 3.10.0 |
| `docs/INVENTORY.md` | This page. | 3.10.0 |
| `docs/RUNTIMES.md` | Exit codes by runtime (WSL, Docker, native Windows). | 3.11.0 |
