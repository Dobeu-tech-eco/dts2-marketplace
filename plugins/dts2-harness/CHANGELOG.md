# Changelog

All notable changes to dts2-harness are recorded here, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
Released versions live in this file. Work that has not been released yet is listed under `## Unreleased` in `README.md` until the release step joins it here.
Entries carry no dates: the repository holds no release tags to take them from.

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
- `merge-go` refuses a lane whose branch changed files outside its owned set (the integration lane is audited against its integration files); `lanes.py audit <manifest> <lane> --head <sha>` shows why.
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
