# Changelog

Command reference for agents: `docs/COMMANDS.md`.

All notable changes to dts2-harness are recorded here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
Released versions live in this file. Work that has not been released yet is listed under `## Unreleased` in `README.md` until the release step joins it here.
Entries carry no dates: the repository holds no release tags to take them from.

## [4.1.0]

Minor release: personal knowledge store, repo review, Composio, agent incidents, fleet view, cooldowns, prompt intake and hooks setup, plus the 3.11.1 son-sandbox fix. Nothing breaking; the 4.0.0 migration steps are unchanged.

### Added

- `/dts2:knowledge` (user only): a private, git-synced store of standing preferences, glossary terms and cross-project learnings, with an optional Cloudflare backend (`scripts/knowledge.py`, `scripts/knowledge_cloudflare.py`); `/dts2:setup` reads it and asks before applying a preference.
- `/dts2:ask-expert` reviews one repo before setup (goal questions, clarity gate, evidence report, optional panel with `panel-tally`) and `/dts2:repo-sweep` runs the quick pass over an owner's repos with one cleanup screen (`scripts/ask_expert.py`, `council.py --allow-research`).
- `/dts2:composio` (user only) connects a Composio account, maps toolkits and connected accounts, and offers to disable overlapping tools without deleting anything (`scripts/composio-setup.py`); `onboard`, `machine-prep`, `improve-scan.py` and `find-skills` take covered tools into account.
- `/dts2:incidents` (`list`, `live`, `brief`, `review`, `resolve`, `promote`, `lessons`) with a read-only `incident-reviewer` agent and an agent telemetry hook that records thin briefs, empty or partial reports, rework and hung spawns; `incident_capture: false` turns capture off. Skill count is now 26 and agent count 8.
- `/dts2:fleet` lists every harness session on the machine and shows a session's handoff, tasks, intake, lanes and cooldowns read-only; `/dts2:check-in all` gathers check-in items from all sessions into one report (`hooks/fleet-session.sh`, `scripts/fleet.py`).
- `/dts2:cooldown` and `scripts/cooldowns.py` track agents paused after a usage limit with their reset dates; `roster.py` and `failover.py` skip cooling agents and `hooks/session-cooldowns.sh` reports them at session start.
- Prompt intake: a `UserPromptSubmit` hook (`hooks/prompt-intake.sh`, `scripts/intake.py`) queues every prompt typed while the harness works as fold, clarify or steer, and `/dts2:steer` is the only command that stops running work to re-plan.
- Onboarding hooks setup (`scripts/hooks-setup.py`, `templates/hooks/`) merges picked hooks into project, local or user settings with a backup, including database guard hooks; `find-skills` now audits every improvement option through the read-only `scripts/improve-scan.py`.
- Handoff and builder gates: H-003 pending plan or ship checkpoint in the handoff, H-004 approved plan counts as the plan checkpoint, H-006 builders run `/improve-codebase-architecture` only when installed.

### Fixed

- 3.11.1 / D74 (son sandbox): the son guard no longer treats an interpreter's script argument inside the plugin's own `scripts/` as a write target, so `lanes.py` runs in a son; `lane_env` sets `CLAUDE_PLUGIN_ROOT` and keeps pnpm's store. Lessons from the incident are recorded.
- Bot-review fixes: fleet broadcast delivery keeps a per-session `.seen.json` marker so no message is skipped; incident lessons keep distinct `K-` ids, project-prefixed promoted keys and the full injected id forms; intake updates run under the file lock and the hook never waits on it; `agent-memory.py` migrates the pre-4.0 managed block in place; `ask_expert.py` backup, delete and panel voting corrected; the hook speed test no longer fails on one slow CI sample.

## [4.0.0]

Plugin renamed from `dts2-harness` to `dts2` so every command reads `/dts2:<command>`.

### Changed

- Breaking: plugin renamed `dts2-harness` -> `dts2` (version 4.0.0); commands are now `/dts2:<command>` and agents `dts2:<agent>`. The plugin folder, the settings file `.claude/dts2-harness.local.md` and the `.harness/` state paths keep their names.
- Migration: existing installs run `/plugin uninstall dts2-harness@dts2`, `/plugin marketplace update dts2`, `/plugin install dts2@dts2`, `/reload-plugins`; settings and `.harness/` state need no change.

### Fixed

- R3 (review findings): `guard.mask_literals` opens a substitution context only for an unescaped `$(`, so an escaped `\$(` or `$$(` no longer hides a following `$(printenv)`; `git commit -m '$(env)'` and the batch-22 nested-quote case are unchanged.

## [3.11.0]

Round 2 hardening: head policy gate, son containment and lifecycle, mailbox, merge and fold recovery, signed receipts, eval A/B runner, report ops and agent completion gates. The optional cross-model review step was skipped for this release by decision of the maintainer; automated CI reviews ran on every PR.

### Added

- Batch 18 (round 2), head policy gate and SDK runner hardening, plus the lead wiring of the wave-1 modules.
- G-70: `scripts/policy_gate.py` + `templates/policy.json` + `hooks/policy-gate.sh` (PreToolUse, head and sons): denies force-push (`--force`, `-f`, `+refspec`, `--force-with-lease`, abbreviated flags), `--admin`, deploy CLIs (vercel, wrangler, fly, netlify, supabase db push), `gh secret`, `vercel env`, a bare `env`/`printenv`, `gh repo delete`; `gh pr merge` and a push to the default branch need `approvals.is_human_approved("merge", <pr or branch>)`; staging everything in an unattended run is red when no secret scanner is installed. Commands are unwrapped first (`bash -lc`, `eval`, `$(...)`, `env -i`, `command`, `sudo`, `npx`, `git -C`, chains, quotes); setting `policy_gate`.
- G-71: SDK runner: per-role `tools=` and `allowed_tools` (only the verifier has Bash), `setting_sources=['user']`, turn and budget caps (settings cache, constants as fallback), a secret scan before `git add -A` (a missing scanner refuses), no Anthropic credential in a second-opinion CLI env, `claude-agent-sdk==0.2.172` pinned.
- Lead wiring: `lanes.py publish <stamp> --lane L` (head only) calls `head_publish.publish_lane`; preflight fails on `auth_problem`, `init_plugin_errors` (stream-json init) and a `git push --dry-run` under the head env; `lanes.py call` runs under `provider_env`; `son_command` uses `son_model(cwd)` and `--wrap` (proc.wrap_son); `son_permission_mode` defaults to `dontAsk`; son brief says commit and stop, the head publishes; council, action-items and lessons `regress` appends are deduped through `state_io.append_event_at` with `event_id(stamp, step, kind, attempt)`; the context-guard hook parks a son through `lanes.py mailbox park`.
- G-70: merge-guard `strip_wrappers` keeps the command behind `env -i`, `env VAR=x` and `env -i VAR=x`; `tests/test_guard_wrappers.py`.
- G-43: status.json carries `"v": 1` and one lane-state enum (`parked` and `stopped` read as `incomplete` plus the old word as the reason); every write carries the lane epoch and a stale epoch is ignored; an unreadable or too-new status reads as `incomplete` (`status-unreadable`, `status-version`); `fold` reads lease files and rebuilds checkpoints from `git log`; `transition` stays the one writer (`--epoch` on `transition` and `heartbeat`).
- G-44: the mailbox (`lanes.py mailbox`): versioned question, answer and need-human ids, send-backs carrying `n` and the epoch, a `merge-go.json` payload `{lane, epoch, verified_head_sha, base_sha}` that the son refuses when its HEAD differs, and a deadline (`mailbox_wait_min`, default 30) on every wait that parks the lane `incomplete` (`mailbox-timeout`).
- G-45: the son contract in the autopilot skill (no own stamp, no writes to the protected records, user prompts become need-human, seat-pool collapse and no browser park, context guard writes `incomplete` plus the session id) with a test that each rule is named.
- G-46: `stop-check` leaves out items tied to a ledgered blocked PR and, with `--base`, reads the end state from the fetched `origin/<base>`; `max_fullauto_loops: 3` stays a resumable park (tested).
- G-47: a lease records its check-in item; `plan` and `lease` refuse an item another live lease holds. The lease does not call `action-items reserve`: that verb reserves ids for new rows, not for existing items, so the contract text says the lease is the hold.
- G-48: `lanes.py override <lane>` logs to `state.md`, is refused in a son, a vote or the council and without `approvals.is_human_approved` (absent module means not approved); out-of-lane requests climb head, vote, council, user.
- G-49: `mailbox rules` digests the rule files (now including `agents/*.md`) at start and before each vote, ship and merge and reports what changed; `agents/*.md` joins the copy-window rule sources of the son-mode test.
- G-50: `dpp_full_ask_each_lane` (plan records it; `lease` refuses a lane until `approve-lane`) and `fullauto_freeze_scope` (the first fullauto plan stores an item hash in `scope.json`; new items go to `pending-items.json`); dpp section 5.5 updated.
- G-51: end-to-end son lifecycle test with a fake son built from `son-command` in a real git worktree: status, question, send-back, merge-go, approval gate, merge order, override refusal and a no-browser park.
- G-30: every hook runs `python3 -I` (session-lessons, stop-checks, pre-compact, session-end); planted `json.py` regression tests.
- G-31: `hooks/lib-settings.sh` parses settings exactly like `lanes.read_setting` (CRLF, inline comments, quotes); contract test over every template key.
- G-32: stop hook runs `node_modules/.bin/tsc` and `eslint` only (never npx), passes `--` before file names, and skips `.harness/checks.sh` in son mode; the eslint config check no longer fails when only one config style exists.
- G-33: stop hook runs under one shared deadline 5 s below the `hooks.json` timeout, saves a partial fingerprint on timeout, and with `stop_checks_block: true` blocks once on a red check (honours `stop_hook_active`).
- G-34: `.harness/cache/` and `.harness/.locks/` added to the ignored paths.
- G-35: context guard looks for `plan.md` in the current run only; `context_guard_stop: true` adds `continue:false` and `stopReason`. Scope cache skipped: the guard's per-call cost is one directory listing.
- G-36: PR receipt chosen by branch-to-stamp mapping (plain, `ship-<stamp>` and lane folders), `gh api .../pulls -X POST` recognised, template push opt-in via `pr_receipt_template_push` (default false, off in son mode).
- G-37: `if` matcher for `gh api *`, context guard also registered on PostToolBatch. Exec-form `args` not adopted: native Windows cannot spawn `.sh` without a shell and tests pin the script path in `command`.
- G-38: unterminated quote around the `task-ledger.py` path in the dpp skill fixed.
- G-39: machine-prep settings and agent-memory files are written through `atomic_write`.
- G-40: README hooks list and settings keys cover every template key (test added); evolve skill uses `bump-version.py` and changelog fragments.
- G-41: workflow actions pinned to full commit SHAs, `shellcheck -x install.sh` added, plugin validate step skipped when the CLI is absent; tests for env-detect, prep-tiers and repo-size.
- Docs: `docs/GUIDE.md`, the agent guide for 3.10 (talking to the harness, which command when, head, son and council flow, 3.10.0 digest), linked from both READMEs and `docs/INVENTORY.md`; root README gains What's new for 3.7 to 3.10, the `dpp`, `dpp-full` and `fullauto` rows and the seven-agent count.
- G-82: Batch 11 (round 2): `lanes.py report` adds run-wide sections (refusals, overrides, merge order and rebases, total spend, check-in delta) and a per-son line (CI result, merge commit, out-of-lane requests); `report-check --stamp` cross-checks the son run records (unlisted lanes, PRs the report never names).
- G-83: Batch 11 (round 2): `OTEL_` joins the son env allowlist prefixes (ruling Q8); no tagging, no bundle cap.
- G-84: Batch 11 (round 2): evolve climbs a hardening ladder (hook, then test, then check, then prose); `pr_payload.py decisions --ledger` and the PR template carry a "Decisions and declined findings" section.
- G-85: Batch 11 (round 2): doctor reports bwrap, socat, auth method and platform; native Windows warns that dpp parks with `windows-native` (ruling Q6); `docs/RUNTIMES.md` maps WSL and Docker exit codes to constants in `doctor.py`.
- G-86: Batch 11 (round 2): `scripts/plugin_options.py` reads `CLAUDE_PLUGIN_OPTION_<KEY>` and `CLAUDE_PLUGIN_DATA`; per-repo settings stay in `.claude`. The manifest `userConfig` block is not added here (plugin.json is outside this batch's files).
- G-87: Batch 11 (round 2): `scripts/receipts_sign.py` adds a hash-chained journal and HMAC signing with a head-held key file the son env never receives (hashlib and hmac only).
- G-78: Batch 9 (round 2): `lanes.py fix-attempt` caps post-merge fixes at `post_merge_fix_attempts` (default 2) and then opens one revert PR (journal-deduped, adopts an open one; falls back to the revert action item and a park); `base-health` records whether the fetched `origin/<base>` is green and `merge-go` refuses while it is red or has moved; `merge-mutex` is the repo-wide mutex from rebase to post-merge PASS, journaled.
- G-79: Batch 9 (round 2): `fold --apply <group> --pr <n>` records `superseded_by` and the new PR on each original; `fold-close` closes the originals with a link comment (state check, then one `gh pr close --comment`, then the journal row).
- G-80: Batch 9 (round 2): integration-lane routing writes a structured record (refusal, reason, alternative, override) to `routing.json`; `status` and `report` print it. G-81 (bundle cap) is not built (ruling Q8).
- G-75: Batch 7/8 (round 2): eval runner A/B mode (`--arm-b-env`, `--runs`, k >= 5 alternating runs) reports median, range, pass^k and a faster / slower / no difference / inconclusive verdict; `scripts/eval_stats.py`, fast tests with a fake runner.
- G-76: Batch 7/8 (round 2): the `skills` npm CLI is pinned (`npx --yes skills@<SKILLS_CLI_VERSION>`); `skills-check.py` no longer self-upgrades while a lane lease is live (`upgrade_deferred`, read-only lease read); `--son-root` reports son-versus-head plugin version skew with the `version-skew` park reason (`scripts/harness_skew.py`).
- G-77: Batch 7/8 (round 2): the hard-coded org string is gone from `skills-check.py` and `skills/evolve/SKILL.md` (the marketplace repo comes from `DTS2_MARKETPLACE_REPO`, `plugin.json` `repository`, or `git remote`); the personal-string scan in `test_orchestration_rules.py` now covers `.py` and `.sh`, plus a test that no script or skill names the org.
- Batch 6 (round 2), agent privilege and completion gates: retryable dispatch failures, least-privilege agent tools, event hooks.
- G-72: `council.py next-round` allocates ballot instances `<step>+<attempt>`; a dispatch error, malformed ballot, HTTP 429 or timeout is retryable (same round, attempt + 1, no vote round); the post-merge re-vote gets its own instance and `postmerge/` folder. Council trigger unchanged (after 3 failed rounds).
- G-73: verifier `tools: Read, Grep, Glob, Bash`; reviewer loses Bash (hook matchers filter by tool name, not agent type, so Bash cannot be scoped). No council or tiebreaker agent files exist. Test pins every agent's tools line.
- G-74: `hooks/subagent-stop.sh` blocks a verifier stop while the newest run ledger lacks a check line (N3); `stop-failure.sh` and `permission-denied.sh` append Handoff action items; PreCompact already runs handoff-write.
- Batch 5 (round 2), son containment: sons commit a branch and the head publishes; protected paths, a human-only approval channel, provider env and ballot provenance.
- G-60: son launch stays non-bare with hooks on (tested by running the configured guard hook); `son_launch.auth_problem` (`claude auth status` via `DTS2_CLAUDE_BIN`) and `init_plugin_errors` (`plugin_errors` in the `system/init` stream-json event) for the preflight.
- G-61: explicit `--allowedTools` (file tools, `git add`, `git commit`, the repo's check commands, harness scripts), `permissions.deny` in `--settings` as the primary control, sandbox `failIfUnavailable` and `allowUnsandboxedCommands: false` pinned by tests; `son_permission_mode` is validated against an allowlist that excludes `bypassPermissions`.
- G-62: `scripts/protected.py` (`protected_paths`, `is_protected`, `diff_touches_protected`, `park_decision`): git common dir config/info/hooks, `.gitattributes`, workflows, checks script, CODEOWNERS, `hooks/`, head-only `.harness` records and `merge-go.md`; a touching diff parks as a Decisions item.
- G-63: `scripts/approvals.py`: human-only channel, `dts2_approvals` in `.claude/settings.local.json` (kinds `recorded_yes`, `unsafe_no_sandbox`, `blocked_pr_done`, `lane_override`, `merge`), write-denied to the model in every son launch; actor logged as `human` or `agent:<session>`.
- G-64: sons are denied `git push*`, `gh pr*` and `gh api*`; `scripts/head_publish.py` (head only) checks protected files, pushes, opens or adopts one PR per lane and merges after the verifier; `pr-receipt.sh` does nothing inside a son; autopilot son mode and dpp text rewritten (intended `lanes.py publish`).
- G-65: unattended merge preconditions in `head_publish.py`: zero reported checks is red, a default-branch merge needs required checks plus a review or a merge queue, a production-deploying merge needs `is_human_approved("merge", <pr>)`, post-merge walkthrough on production is flagged read-only (`DTS2_WALKTHROUGH_READONLY`).
- G-66: `head_publish.py bootstrap`: idempotent per-lockfile install, a sanitized `son.env` of non-secret `.env.example` keys, missing secret names filed as Secrets items; the resolved-blocked-PR re-verify path is untouched.
- G-67: the son env allowlist (`son_launch.provider_env`) now applies to `roster.py command` (`clean_env`, `shell` starts `env -i`) and the SDK second opinion; `scripts/provider_report.py` adds a provider-neutral brief footer and a validator for the fenced JSON report.
- G-68: `scripts/ballot_dispatch.py` runs each council seat and writes `<ballot>.dispatch.json` (argv, model, session id, sha256); `council.py tally` does not count a ballot without a valid record; Claude seats run with `--json-schema` and `--restricted`.
- G-69: SessionStart lessons, state and action items are printed inside the untrusted-content fence, capped at 4000 characters (`council.py wrap - --max-chars`).
- Batch 4 (round 2): the son process lifecycle. A son now starts in its own session, writes `son.json` (pid, pgid, argv, session id) and, when it ends, `exit.json` (code, signal, cost, session id, reason).
- G-52: a pre-assigned `--session-id` (uuid4), stream-json output, and the old process group stopped (SIGINT, then SIGKILL) before a lane is dispatched again. `proc.wrap_son(cmd, lane_dir, session_id)` is ready for the planner's `son-command` to call.
- G-53: `lanes.py reconcile` applies the deterministic mappings: son exit with no final phase -> incomplete (reason from `exit.json`), merged on GitHub -> done, quiet clean lane -> incomplete (stalled); only judgement calls return to the head.
- G-54: verified the `(stamp, kind, lane, attempt)` dedupe in the merge journal and builders log, and PR check-then-act; the `council.md`, lessons and action-item appends are not deduped yet (see the report).
- G-55: `lanes.py gc` closes expired leases of crashed runs; `preflight` and `spawn --resume` run it; tests for heartbeat renewal and TTL expiry.
- G-56: max-turns and "Budget limit reached" results end the lane incomplete; SIGINT then SIGKILL after 30 s (`timeout -s INT -k 30`); `CLAUDE_CODE_RESUME_INTERRUPTED_TURN=1` in the son env; the harness retries an overload only after the CLI's `api_retry` is exhausted; the heartbeat comes from stream-json events.
- G-57: `son_stream.detect_stuck` marks a lane stalled after 4 identical action/observation pairs, 3 failing identical actions or 6 ping-pong actions.
- G-58: `lanes.py wait <stamp> --timeout` blocks on `exit.json` and phase changes (inotify, else sleep-backoff); the dpp head calls it once instead of polling `status`.
- G-59: `son_model` setting (default `opus`) replaces the fixed son model; council head and alternate model ids come from one place (`profiles/agents/claude.json`), checked by a test.

### Fixed

- Verifier stop check reads the current run's ledger only; a run with no ledger yet is missing every check instead of passing on an older run's ledger.
- `merge-go-step` applies the same base-health and merge-mutex refusal as `merge-go` (a `revert-<lane>` step acts for the mutex holder and is not held by the red base it repairs).
- `receipts_sign.py` fails closed when `DTS2_PR_RECEIPT_KEY_FILE` is set but unreadable or empty; unset stays unsigned.
- The revert branch is reset with `git worktree add -B` and pushed with `--force-with-lease`, so a retry after a failed push or `gh pr create` works.
- Base check runs are read with `gh api --paginate --slurp` and the pages are merged, so a failure past the first 30 runs is seen.
- `council.py next-round` instance ids count up per step across rounds; round 2 no longer reuses round 1's id.
- `report_check` matches a PR number with a non-digit boundary (`#7` no longer matches `#70`).
- Stop checks skipped for a son save a `partial` fingerprint, so the next Stop on the same tree runs the checks.
- `head_publish.py` treats `DTS2_SON_BRANCH_PREFIX` as a son signal, like `lanes.records.inside_son`.
- Tests: `import unittest.mock as mock` and `assertLessEqual` in batch 9 and 11 tests (CodeQL notes).
- Review A: `proc.run_once` streaming path keeps its deadline while draining pipes held by descendants (kills the group, no blocking close); documented the two ignored exceptions in `proc.py`.
- Review B: `Inotify.wait` ignored `BlockingIOError` is commented.
- Review C: `detect_stuck` compares a SHA-256 of the full observation, not a 2000-char prefix.
- Review D: a mailbox timeout park carries the question's epoch; a stale question no longer parks a re-leased lane.
- Review E: the son contract reports `pr-open` first, then waits for the grant (no circular wait with `next_to_merge`).
- Review F: `plan` filters by the frozen fullauto scope before the cap and conflict selection; excluded items are recorded as pending.
- Review G: the no-phase heartbeat checks the epoch under the status lock and does not renew a lease when stale.
- Review K: the context guard resolves the active run from the `dts2/<stamp>/` branch before looking for a plan.
- Review P: sons cannot write `.claude/settings.local.json` (sandbox write deny) and `protected.py` refuses a publish diff that touches it.
- Review M: `test_batch17_mailbox.py` and `test_batch5_containment.py` use `import unittest.mock as mock`.
- Review H: the autopilot gate and preflight docs dispatch council seats through `ballot_dispatch.py`, so ballots carry their `.dispatch.json` record.
- Review I: `head_publish.py` refuses publish and merge when `DTS2_SON` is set; the lockfile stamp hashes file contents (sha256).
- Review J: the protected hooks glob matches a `hooks/` folder at any depth, the repo root included.
- Review N: the publish diff is read with `--no-renames`, so a renamed protected file is seen at its source path.
- Review O: the son Bash allowlist covers the plugin's own scripts directory only, and `head_publish.py` is denied.
- Review Q: publish adopts only an open PR; a closed or merged PR is ignored and a new one is opened.
- Review R: the merge default branch comes from `merge.default_branch` in the config, falling back to `main`.
- Review L: `pr-receipt.sh` treats `gh api .../pulls` with `-f`/`-F`/`--field`/`--raw-field`/`--input` and no method as a PR create; an explicit `-X GET` stays a GET.
- Review S: `stop-checks.sh` runs no repo-provided binary (checks.sh, tsc, eslint) when `DTS2_SON` is set, and prints `skipped: son`.
- Review T: a failed check saves a `partial` fingerprint, so the next Stop runs the checks again.
- Review U: the Stop payload is read before any check step runs, and check steps run with stdin closed, so `maybe_block` always sees it.
- Review V: no `A && B || C` in the hook scripts (SC2015); `context-guard.sh` and `stop-checks.sh` use if/else.
- Review K (after merging main): the active run from the branch name is preferred; otherwise main's newest-run rule applies.
- Policy gate and merge guard: bundled `env` flags (`env -iu PATH git push --force`) no longer hide the command word, so the force-push rule still applies (review findings).
- Policy gate: a flag-only deny rule (`gh ... --admin`, `vercel --prod`) fails closed when an argument is a shell expansion, with or without a sub-command.
- Policy gate: `$(...)` and backticks inside single quotes are text, so `git commit -m '$(env)'` is no longer denied as an environment dump; double-quoted and bare substitutions are still checked.
- Policy gate: a rule's sub-command matches only at the sub-command position, so `gh pr create --title secret` is no longer denied as `gh secret`.
- G-54 dedupe: `lessons.py regress`, `action-items.py add` and `council.py` keep the dedupe id only after the write succeeded; a failed first attempt no longer turns the retry into a silent duplicate.
- `council.py next-round` seeds the instance counter from earlier allocations in `instances.json`, so a resumed run never reuses an instance id.
- Preflight head push probe runs `git -c core.hooksPath=/dev/null push --dry-run --no-verify`, so the repo's `pre-push` hook never runs during the probe.
- `lanes.py publish` is head-only: denied in a son's Bash (guard and launch deny list), refused for a son, voter or council role even without env markers, and `lanes.py call` refuses a wrapped command that sets or unsets `DTS2_SON*`.
- Policy gate: `mask_literals` keeps a quote stack, so a single quote inside a nested `$(...)` within double quotes is literal and `echo "$(echo "'$(printenv)'")"` is denied again as an environment dump; `git commit -m '$(env)'` stays allowed (review findings).
- Policy gate: `sub_slack` skips each leading `--name value` flag value, so `vercel --token x --scope y env ls` matches the `vercel-env` deny rule again; `gh pr create --title secret` stays allowed (review findings).

## [3.10.0]

Parallel autopilot hardening: lane lifecycle, son containment, merge ordering, council seats, supply chain, docs inventory.

### Added

- Lane lifecycle in `scripts/lanes.py`: `transition` is the sole writer of a lane's phase (one `LEGAL` table; a son may report only pr-open, done, blocked or incomplete), plus `heartbeat`, `budget`, `merge-order`, `merge-go --head <sha>`, `merge-done`, `shutdown` (graceful end of a run), `reconcile` (asks GitHub about each lane's branch and returns one action per lane; also reconciles a standalone `dts2/<stamp>/step-<step>` branch), `merge-resume`, `fold-done`, `walkthrough-failed`, `run-record`, `builder`, `run-resume`, `amend`, `merge-plan`, `merge-go-step` and `loop`. dpp, autopilot and fullauto call them instead of describing the steps. (G-13, G-14, G-15, G-17, G-29, A4, B6)
- Per-run merge journal (`merge-journal.jsonl`) of grants, merges, fold plans and shipped fold groups; `lanes.py merge-resume` settles a merge a dead head left half done. Typed `run.json` (`RunRecord`) and `builders.jsonl` replace Markdown parsing on resume. (G-15, G-17)
- Leases carry `expires_at`, `ttl_s` and the `session_id`; a heartbeat renews them, expired leases of other runs stop blocking, and the overlap check and lease write run under one admission lock. Lease epochs (`--epoch`) refuse stale writers. SessionEnd releases the leases stamped with the session and refreshes the handoff. (G-16, A3, Q-16)
- Planning: lanes may declare `provides`, `consumes` and `stubbed_on` (`plan_graph.py merge-order` records provider-first order); owners may be `dir/` prefixes or globs; areas come from package roots; `lanes.shared_files` in `.harness/config.yaml` routes globs to the integration lane; `check` routes lockfiles, migrations, route tables and barrel `index.ts` to a final integration lane; a PR bundles at most 5 tasks; `lanes.py plan` adds a `graph` block (cycle check, critical path) and `plan_graph.py brief` prints the six-section lane brief. (G-25, G-26, G-27, G-28, B6, Q-22)
- Son containment: sons launch without `--bare` and with `--setting-sources local`, `--permission-mode dontAsk`, tool allowlist and deny list, explicit sandbox settings with default-deny egress, empty `--mcp-config` and `--plugin-dir`, and an allowlisted environment (`scripts/son_launch.py`; `DTS2_SON_ENV_PASS` names extra variables). `scripts/guard.py --mode son` is the PreToolUse deny hook. `lanes.py preflight` runs the real son launch plus `git ls-remote origin` and pins `claude --version`; `spawn` refuses a different version, a `claude` older than 2.1.242 and a second unattended son with `sandbox.enabled: false` unless `--unsafe-no-sandbox` is passed. Sons stop at `pr-open`; the head merges. (A8, A11, SE-2/SE-4)
- Hard caps and fallback: `lanes.py spawn` passes `--max-turns`, `--output-format json`, `--fallback-model` (chain of up to 3) and `--max-budget-usd` with the lane's reserved share; new `budget:` config block (`max_turns`, `max_wall_minutes`, `max_rounds`, `max_fullauto_loops`, optional `max_usd`); `spawn --resume` charges only new spend; `lanes.py call --cost-source {claude,none}`. Per-lane `PORT`, `COMPOSE_PROJECT_NAME` and `DTS2_DB_NAME`, a shared cache under `.harness/cache`, and `gc.auto` 0 for the run. Every CLI model call goes through `scripts/model_call.py` (machine-wide `supervisor.max_model_calls`, 429 backoff, strict JSON parsing); `max_builders` defaults to 4. (A5, A6, A7, N1, SE-2)
- Merge guard: PreToolUse hook `hooks/merge-guard.sh` and `scripts/guard.py` gate `gh pr merge`, non-GET `gh api` merge paths, graphql `mergePullRequest` and pushes to protected branches unless a `merge-go.md` names the head and base commits; force-push is always refused; denials go to `.harness/merge-guard.log`. Runs merge into `merge.target` (default `dev`); the default branch needs `lanes.py merge-target --yes-default-branch`. (Q-15, G-18, A9, B5)
- Council: `scripts/seat_swap.py` substitutes the next provider when a seat times out and notes two identical rounds; `council.py swap` and `council.py identical` are wired into the run review text; `council.py blind` strips author identity and shuffles option order per voter; `council.py wrap` fences untrusted ballots and `council.py tally` accepts only a strict verdict first line; council model ids moved to `profiles/agents/<provider>.json` under `councilModels` with a `freshness` entry per provider in `council.py seats`. (B7, B14B, B2, A9, B8)
- Checks gate: `scripts/checks.py` runs tests, typecheck, lint, a secret scan and a scope check before any vote and records each in `.harness/runs/<stamp>/ledger.jsonl`; `checks.py gate`, `council.py route` and `check-decision --ledger` act on it. The verifier splits into an evidence scout (`Mode: evidence`, `checks.py scout-check`) and a frontier verifier. (A12, N3, B3)
- Builder audit and plan gate: `scripts/builder-audit.py`, `scripts/plan-gate.py` (PLAN GATE PASS or FAIL), a mandatory `## Foundation` section (`wave: 0`), `repo-size.py --json` heavy files and suggested sections, `review_split.py`, a fixed `FLAGS:` block with `flags_collect.py`, `rollback_ref.py`, a `fixer` agent with an `escalation` seat in `delegate.py` for fix round 2, and the shared `ownership_audit.audit` core. (AA-1 to AA-10, G-24)
- State port and shared modules: `state_io.py` (path names, `Store` with `FileStore` and `MemoryStore`, `"v": 1` records, `migrate-all`, atomic writes, `Stamp` and `LaneId` in `state_ids.py`), `proc.py` (`Runner`, `FakeRunner`, `DryRunRunner`), `mdparse.py` and `contracts.py`, `miniyaml.py`, `_load.py` and `settings_cache.py`, `profiles.py`. (G-8 to G-10, G-19, G-21, G-22, A3, AC-1, AC-2)
- Context and memory: lessons take `{paths: ...}` globs and `lessons.py` tracks `promoted_at`, regressions and 90-day pruning; PreCompact refreshes the handoff and SessionStart after a compact prints a resume pointer; SubagentStop checks builder, reviewer and verifier reports with `contracts.parse_report`; `findings.py` calibrates severities; one-page lead brief (`briefs.py lead-brief`), ~4 KB son brief (`templates/son-brief.md`, `briefs.py son-brief`, `prefix`, `dry-run`) and a cached prompt prefix for sons. (Q-5 to Q-8, Q-11, Q-21, B1, N5)
- Production readiness: `scripts/prod-scaffold.py` writes CI, `RUNBOOK.md` and `ops/` notes for the target app, `scripts/app-type-detect.py` names the app type, `end-state.md` gains a Production readiness table, and `setup` offers a Dependabot or Renovate config. (C1 to C7, D4)
- Tooling: `scripts/run_report.py` and `scripts/run_metrics.py` (lanes, tokens, wall-clock, 3x-median warning), `scripts/walkthrough_fallback.py` (Playwright fallback), `scripts/bump-version.py` and Makefile targets `package`, `test`, `check-version`, `make doctor`, `evals/run.py`, Hypothesis property tests, `ARCHITECTURE.md`, and a CI workflow (Python 3.10 to 3.13, ruff, shellcheck). (N6, SE-1, B10, B9, A1, B1, D2 to D4, N7)
- Docs inventory: `docs/INVENTORY.md` lists every skill, agent, hook, script and Makefile target, including all 35 `lanes.py` subcommands, with a "Called by" column and a "Changed in 3.10.0" section; `tests/test_inventory_complete.py` fails when an entry is missing. `ARCHITECTURE.md` describes the `scripts/lanes/` package, `state_io.py`, the plan graph, briefs and hook entry points.
- `merge-go` refuses a lane whose branch changed files outside its owned set (the integration lane is audited against its integration files); `lanes.py audit <manifest> <lane> --head <sha>` shows why. A rename is audited as both its old and new path, and owned paths written with `./` or backslashes still match.
- Merge-order property tests (random dependency graphs and merge-go/merge-done interleavings).

### Changed

- `skills/run`, `skills/autopilot` and `skills/setup` are short router `SKILL.md` files plus phase files read on demand; text moved, content kept. (B1, Q-10)
- `lanes.py` is a thin CLI over the `scripts/lanes/` package; the lane lock moves into the state port (`Store.lock`) with stale-lock reclaim and `renew()`, and `State.acquire_lease` and `release_lease` require `epoch=`. (AC-3, G-11)
- Branch names no longer nest: `dts2/<stamp>/main`, `main-b<n>`, `lane-<x>`, `lane-<x>-b<n>`, `step-<step>`; `lanes.py branch-check` needs git 2.38 or newer. (A2)
- Ledger and metrics rows share one event shape `{v, ts, run, lane, kind, id}`; an event written with a caller-chosen id is recorded once. (G-23)
- `delegate.py` owns the complexity policy; mechanical sections and phase-4 notes dispatch the builder with `model: haiku, effort: low`. (AC-2, AA-8)
- Skill and agent descriptions are cut to about 250 characters; `scripts/context-tax.py` exits 1 above 6000 tokens; `disable-model-invocation: true` on dpp-full, fullauto, machine-prep, sdk, onboard and model; agents get `maxTurns`, `effort` and `color`, and the verifier cannot write files. `hooks.json` narrows the context guard and `pr-receipt.sh` matchers. (Q-1 to Q-4, Q-9, Q-12, Q-13, Q-19, A10)
- `docs/INVENTORY.md` and `ARCHITECTURE.md` rewritten from the plugin files. (docs refresh)

### Fixed

- `lanes.py lease` and `plan` fail closed when gh is missing or cannot answer; `--no-prs` skips the check on purpose. (G-20)
- Merge order honors `merge_after` in `valid_order`, `merge_sequence`, `unmerged_needs` and `merge-plan` reordering; `reconcile` records a merged lane in `merge-order.json`, never resumes a lane under a running son, and bumps `resume_count` only on a real move to orphaned. (merge-after-order, followups-2, A4)
- Sons no longer park at `pr-open` on the head-only `reconcile`; standalone steps re-check `gh pr view` on resume. (autopilot-reconcile)
- `state_io` lock drop and touch can no longer free or refresh a successor's lock, and a reclaim on the last try no longer raises `LockBusy`; `append_text` with a `header` writes the header atomically; `test_resume_charges_only_the_difference` no longer flakes. (nits, fix-flaky-append-resume)
- `roster.classify_dispatch` treats exit 143 as outcome `timeout` with `seatFailed: true` so council can swap the seat. (roster-143)
- `builder-audit` sees both paths of a rename and untracked files in new folders; `plan-gate` catches intersecting globs and requires `complexity:` on Foundation; `flags_collect` skips blank lines after `FLAGS:`; `review_split` grouping, `graph_lease` lockfiles, the final-review digest truncation note, `disjoint_lane_count`, the compact resume pointer, run report wall-clock and `learn` pruning approval corrected. (b14a-followups, followups, followups-2)
- `subagent_report.already_blocked` handles an unwritable marker file with a documented fallback. (closing-a)
- Review fixes across the checks gate, scope check, blind/redaction, prod-scaffold, app-type detection and skill-pin handling (details in the commit history). (C1 to C7, B4/B8)
- The onboard skill counted six agents; there are seven.

### Security

- Son containment, the merge guard and fenced council ballots (see Added) limit what an unattended son can run, push and merge; `GH_TOKEN`, `GITHUB_TOKEN`, `SSH_AUTH_SOCK` and cloud credentials are absent from a son's environment unless `DTS2_SON_ENV_PASS` names them. (A8, Q-15, A9)
- Supply chain: companion skills can be pinned to a commit with `pin: <40-char sha>` in `.harness/keep.yaml` (a malformed pin fails closed); `npx skills update` no longer runs anywhere; `skills-check.py` writes `.harness/skill-updates.json` proposals and applies one only through `--fix --apply-update NAME=SHA` after an explicit yes; the pre-check never deletes or overwrites a git-tracked skill file. (B4)
- Check logs and action items are redacted of key-shaped strings, bearer tokens and URL passwords; missing env vars are recorded by name only; the shared PR template org is no longer hard-coded. (A12, B8)

## [3.9.1]

- dpp end-to-end fixture test (two blocked lanes folded onto one PR, items marked done, resume finds the PR). Fix: task-ledger.py now writes one row per PR, so a PR folded from several lanes resolves only when every lane's items are done.

## [3.9.0]

- parallel autopilot. New `/dts2-harness:dpp`, `/dts2-harness:dpp-full` and `/dts2-harness:fullauto`: a head plans lanes from the check-in list (`lanes.py plan`, feasibility `check`, `estimated_spend` per lane, outside-check-in marker, `--full` delegation scan that never pads and reports `no further parallel work found`), gets approval (user, or autopilot vote and council), starts one headless autopilot son per lane, supervises (`lanes.py status` marks a lane stalled past `builder_timeout_min`, `sendback` refuses a third, `release` frees a lease, head-answered questions never reach the user), serialises merges with `merge-go.md`, folds lessons and action items back, folds blocked lanes into the fewest PRs (`lanes.py fold`), writes `dpp-report.md` (`lanes.py report-check` enforces every lane section plus `## Spend` and `## Task ledger`) and runs `task-ledger.py` last; `resume` merges PRs whose `TASK_` items are done first. `fullauto` loops check-in between rounds and stops via `lanes.py stop-check` when nothing is outstanding and every lane is done or blocked in the ledger.

## [3.8.1]

- the council only sits after three failed rounds of the normal vote. New `council.py eligible` reads the step's vote history and allows the council only when three complete rounds of the normal panel vote on the same ballot (plan or build), each with its three panel votes and any tiebreak that was due, have all failed to pass; anything less returns `eligible: false` with what to do instead (finish the round, or fix and vote again). `council.py dossier` enforces the same rule and refuses to build a council dossier early. A failed or invalid Fable tiebreak no longer jumps straight to the council: it counts as a failed round and gets a fix round like any other. Each ballot gets its own three rounds before escalation.

## [3.8.0]

- autopilot council. When three rounds of voting do not settle a step, autopilot convenes a council instead of parking: five frontier seats spread across as many providers as are usable (claude, codex, gemini, grok, cursor, muse; `council.py seats` picks them, a `council:` block in `.harness/config.yaml` sets order, exclusions and extra models, and a provider takes a second seat only with a different model such as Claude Opus 5.5 plus Claude Fable 5.0, never Fable 5.1) each read a dossier of the step's full history, every ballot, finding and note from every participant from the first plan vote to the last fix round, and vote. Every seat that votes against the majority writes a dissent brief. Claude Fable 5.1 as head of council then decides: run more fixes, strike items (each becomes a Decisions action item), or approve, and its decision record must answer every dissent with the update made for it and state how many history entries it reviewed. New `scripts/council.py` builds the dossier, tallies the ballots, and rejects a decision record that skips a dissent or the history. Every council is written to the harness record: `council.py ledger` appends the vote, each member's vote and reasons, every dissent brief, the decision and the head of council's brief to `.harness/council.md` (committed on the step branch), with a line in `.harness/state.md` and a lesson in `.harness/lessons.md`. `roster.py command` gains `--model` so a doubled seat runs its exact model. The head of council's brief goes in the PR, the receipt, check-in and the final report so the user sees why autopilot went the way it did. Bounded: one council per step, at most two head-of-council fix rounds, otherwise park; a council never overrides a hard stop or branch protection.

## [3.7.2]

- the pre-check never deletes or overwrites a git-tracked file. `npx skills update` had deleted committed skill files (vendored Stripe skills under `.claude/skills/`); now every mutating `npx skills` call runs under a snapshot that puts tracked skill files and a tracked `skills-lock.json` back byte-for-byte (uncommitted edits included) and drops files the CLI added inside a tracked skill, while untracked skills still update normally. A retired or swapped-out skill with tracked files is skipped, not removed. When the repo is under git but `git ls-files` fails, the update is skipped (fail closed). Applies to `--force-full` too. Skips are reported in `skills.tracked_skipped` (`name`, `step`, `reverted`) and `skills.tracked_check`.

## [3.7.1]

- the pre-check splits into a once-a-day freshness sweep (marketplace refresh, `npx skills update`, gone-upstream checks, harness-version check — the network-heavy work, gated by `.harness/.skills-checked`) and a per-run fast path that only checks skills are present, installs any missing, and acts on a detected upgrade. Cuts per-run pre-check wall-clock by ~90%; `--force-full` forces the sweep. `.harness/.skills-checked` and `.harness/upgrade-from.txt` are gitignored.

## [3.7.0]

- pre-check before every run command (`scripts/skills-check.py`): installs every companion and keep.yaml skill with `-a claude-code --copy -y` (a bare install's symlink silently failed on Windows, so companions never reached Claude Code), removes retired skills, `npx skills update`, swaps a skill gone upstream for the highest-install live alternative, refreshes plugin marketplaces, and when a newer harness is published saves the spot and upgrades in place; the next run finishes it, so `/dts2-harness:upgrade` is removed. `resolving-merge-conflicts` (removed upstream by mattpocock) retired for `warpdotdev/common-skills@resolve-merge-conflicts`. New `/dts2-harness:ship` (user-initiated PR with pre-checks, receipt, richer PR template, and a PR/branch sweep down to main and dev), `/dts2-harness:feature` (roadmap a feature, scoped deep interview, every plan doc synced), and `/dts2-harness:autopilot` (no human checkpoints; three frontier providers must agree on plan and build, Claude Fable 5.1 breaks a split; one PR per step merged on green CI; progress in check-in). Evolve runs automatically after every ship on open harness lessons.

## [3.6.3]

- codex tiers are pinned from a ChatGPT Pro model list (2026-11-03): frontier gpt-6-astra, standard gpt-6.1-sol, economy gpt-6-luna. `codex exec` gets `-m` and `-c model_reasoning_effort` so a global config.toml high does not apply to every seat. Builders stay on standard or economy at low–high; sign-off may use xhigh; max and ultra only when explicitly requested. An unpinned run (default gpt-6.1-sol) reports as the standard tier. Other agent profiles were already tiered and were left unchanged.

## [3.6.2]

- the builder finalization pass uses `improve-codebase-architecture` scoped to the builder's file set, because upstream retired `request-refactor-plan`. A manual scoped simplification pass is the documented fallback. The hard-cap `diagnose` companion (renamed upstream to `diagnosing-bugs`) becomes a fresh `diagnosing-bugs` pass.

## [3.6.1]

- gtm is self-sufficient: auto-installs marketing-skills, runs a deep-dive (optional deep-interview re-run), selects the applicable skills, and runs them as one seamless pass.

## [3.6.0]

- strict delegation: frontier models only for advisory and sign-off, builders run the cheapest capable model at a complexity-scaled effort (new delegate.py); effort factored into the calc; Muse Code (Meta) added to the roster; plus /dts2-harness:upgrade (one-command in-place upgrade) and user-selectable lead provider via /dts2-harness:model; auto hand-off and lead failover on a usage/token-limit stall; every detected agent gets a seeded project memory file at scaffold; /dts2-harness:find-skills rescans and suggests skills on demand; request-refactor-plan finalization pass before tests; auto diagnose at the hard 3-round fix cap; loop-me check-in on run trigger; setup-pre-commit before every commit; code-review on first contact with a new repo; /dts2-harness:check-in shows complete vs outstanding against the end state; exhausted-budget effort is clamped to the profile's levels.

## [3.5.0]

- new muse profile; per-role commands via `roster.py command` (grok review in plan mode, grok builders edit without a shell); gemini runs headless agy in plan mode on gemini-3.8 models, in the run skill and the SDK second opinion; codex drops the gpt-5-codex pin and reads stdin from /dev/null, and the lead commits for it; `roster.py classify` treats 402/429 as unavailable for the run and sends copilot's security seat to grok on the context-budget error; verifier HEAD guard; Supabase CLI route for database builders; Vercel verified-commit cancels are a note; handoff picks the newest stamped run. Hardening from review: grok seats deny Bash/MCP/subagents (reviewers also Edit/Write) and run with GROK_WORKFLOWS=0; grok builders edit only inside the working directory and never under .git, .grok, .claude or .cursor; prompts travel as files and `roster.py command` returns a quoted shell line; muse builds and gives second opinions but never takes a review seat (its second opinion runs with write, shell and web tools off); `classify` now requires `--exit-code`, reads only error lines from the tail of a failed run, and treats muse's recorded 402/429 forms as decisive at any exit.

## [3.4.0]

- companion skills from mattpocock/skills wired into setup (grill-me, improve-codebase-architecture, writing-for-agents) and run (pr, resolving-merge-conflicts), installed per project when first needed and kept via keep.yaml, ask-matt → research for user questions, and diagnosing-bugs before the second fix round.

## [3.3.1]

- gemini (Antigravity agy) and grok profiles now allow builder and reviewer roles besides second-opinion, per owner ruling D23.

## [3.3.0]

- end-to-end Sections map in the interview; continuous dispatch: builders stay busy on ready sections, stalled ones are parked with action items.

## [3.2.0]

- scope check with auto-pivot to the workspace root; context guard hook that stops a run and re-runs setup on a context spike or when started inside a member repo; project keep list (.harness/keep.yaml) so re-running setup never drops chosen plugins, skills (incl. npx skills add installs) or agents.

## [3.1.0]

- Rules 9 (orchestration) and 10 (branches, worktrees, PRs) in discipline.md; worktree per builder by default in git repos; `run review-pr <n>`.

## [3.0.2]

- Gemini is reached through the Antigravity `agy` CLI; roster finds agent CLIs that are off PATH via per-profile `searchPaths` and a `DTS2_BIN_<NAME>` override.

## [3.0.1]

- learn skill description no longer contains angle brackets (claude.ai plugin upload rejected it).

## [3.0.0]

- end-state interview, Plan and Ship checkpoints, agent roster, harness discipline, deployment verification, action items, GTM, machine-prep tiers. See the root README.

## [2.1.0]

- machine-prep handles claude.ai synced plugins, org-required plugins, and project-level overrides.

## [2.0.0]

- first release.
