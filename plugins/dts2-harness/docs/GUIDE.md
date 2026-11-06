# dts2 4.0 agent guide

> Migrating from dts2-harness (old name): the plugin is now `dts2`, so commands are `/dts2:<command>`. Run `/plugin uninstall dts2-harness@dts2`, `/plugin marketplace update dts2`, `/plugin install dts2@dts2`, `/reload-plugins`; settings and `.harness/` state are unchanged.

How to talk to the harness, which command to reach for, and what changed in 3.11.0 and 3.10.0. Written for an agent (or a person) who lands in a repo that uses the harness and needs to act without reading every skill file. The exhaustive reference is `INVENTORY.md` (every skill, agent, hook, script and `lanes.py` subcommand); the internals are in `../ARCHITECTURE.md`; the full release notes are in `../CHANGELOG.md`.

Contents: 1 Talking to the harness, 2 Which command when, 3 The head, son and council flow, 4 Rules every agent follows, 5 Release history (3.11.0, 3.10.0), 6 Where state lives.

## 1. Talking to the harness

The harness is a Claude Code plugin. Every entry point is a slash command `/dts2:<skill>`; there is no other interface. Twenty-two skills exist (section 2). Seven agents (`lead`, `builder`, `fixer`, `reviewer`, `verifier`, `scout`, `auditor`) are dispatched by the skills, never typed by the user; an agent that needs one calls the Agent tool with `subagent_type: dts2:<name>`.

Six skills run only when the user types them (`disable-model-invocation: true`): `dpp-full`, `fullauto`, `machine-prep`, `model`, `onboard`, `sdk`. The others may be invoked by the model when the conversation calls for them.

Install and update:

```
/plugin marketplace add Dobeu-tech-eco/dts2-marketplace
/plugin install dts2@dts2
/plugin marketplace update dts2      # then /reload-plugins
```

Arguments go after the command name, separated by spaces. Quote a task that contains spaces. Examples:

```
/dts2:run add rate limiting to the public API
/dts2:run section 4
/dts2:run resume
/dts2:run add secret STRIPE_KEY
/dts2:run review-pr 52
/dts2:autopilot 3-5
/dts2:autopilot feature "export orders to CSV"
/dts2:autopilot --son 20261105T0412/lane-b
/dts2:dpp dry-run
/dts2:ship dev
/dts2:feature "nightly report emailer"
/dts2:action-items done S-3
/dts2:learn promote L-012
```

Scripts are never typed by the user. Skills call them as `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" <subcommand> ...`; each prints one JSON object on stdout. `INVENTORY.md` section 4 lists every script and flag.

The harness answers in a fixed shape:

- A run ends with a receipt (`.harness/receipts/<stamp>.md`) and a PR link, or a parked state with the reason.
- A checkpoint is a question with the plan or the ship summary and the words `approve`, `edit` or `stop`. Under `run` the user answers; under `autopilot` three frontier providers vote and Fable 5.1 breaks a tie.
- Anything that needs a person is an action item (`/dts2:action-items`): a missing secret, a decision, a handoff, a deploy step. The item names the command that resolves it.
- Progress is always readable without side effects: `/dts2:check-in`.

### Talking while it works

A prompt typed while a run is going is not lost. The `UserPromptSubmit` hook appends it to the intake queue (`.harness/intake.jsonl`, shown in `.harness/intake.md`) and classes it:

- **fold**: an addition ("also add a CSV export"). It goes into the ledger and the agent keeps working.
- **clarify**: words that may conflict with the plan ("stop", "cancel", "instead", "revert", "don't", "change direction"). The agent asks at the next safe point, before it acts. Clarity below 60 of 100 allows at most two short questions; then the item is set on the best reading, with the assumption stated, and work continues.
- **steer**: `/dts2:steer <new direction>` (or a `steer:` prefix). The only thing that stops running work: the current atomic step finishes, nothing new is dispatched, a handoff is checkpointed, open intake items are reviewed, the plan is redone for the new direction, and the run resumes after one short confirmation.

Other slash commands are ignored by intake, and a prompt is never blocked. Turn intake off with `intake: false` in `.claude/dts2-harness.local.md`. See the queue with `intake.py list`.

## 2. Which command when

For exact syntax (required arguments, flags, who may run it, what it writes) and one-line examples of every command, read `COMMANDS.md`; the table below only says which command to reach for.

| You want to | Use | Notes |
|---|---|---|
| Understand the harness, pick a starting point | `onboard` | Explanation only. Changes nothing. |
| Prepare a new computer once | `machine-prep` | Audits installed agent tooling, prunes to the blueprint keep-set with a settings backup. Once per machine. |
| Start a repo or workspace on the harness | `setup [path ...] [--scaffold-only]` | End-state interview until the user approves `.harness/end-state.md`, then scaffolds `.harness/`. Several paths means batch scaffold. |
| Do one task with a human in the loop | `run <task>` | Scout sizes, lead plans (Plan checkpoint), builders build, reviewers and verifier check, ship (Ship checkpoint). The default for day-to-day work. |
| Continue a parked or interrupted run | `run resume` | Reads the handoff and the run record (`lanes.py run-resume`). |
| Build one section of the approved end state | `run section <#>` | Section numbers come from `end-state.md` and `check-in`. |
| Record a secret the run is waiting on | `run add secret NAME` | Never paste the value in chat; the item tells you where it goes. |
| Review someone else's PR with the harness reviewers | `run review-pr <n>` | Read-only; writes findings, merges nothing. |
| Plan a feature without building it | `feature <description>` | Clarity score, scoped interview when unclear, end-state updated, plan PR. Follow with `run section` or `autopilot`. |
| Build several steps with no human checkpoints | `autopilot <steps>` | Steps are section numbers (`3,4,7`, `3-5`), action-item ids, `feature "<text>"` or quoted tasks. One branch and one PR per step, merged on green CI. Three-provider gate; council after three failed rounds. |
| See where autopilot is, or pick it up again | `autopilot status`, `autopilot resume` | |
| Run many autopilot lanes at once | `dpp [dry-run] [--full] [resume]` | A head plans lanes from the check-in list, you approve the lanes, one headless son per lane, the head merges in order. `dry-run` plans only. |
| Same, and let the head fill lanes itself | `dpp-full` | `dpp --full`: adds a delegation scan and keeps dispatching without a new approval. User-typed only. |
| Wait for sons without polling | `lanes.py wait <stamp> --timeout N` | Head only. Returns on a phase change or a son's exit. |
| Answer a son, or see what a son asked | `lanes.py mailbox <op> <stamp>` | Ops: ask, need-human, answer, check, wait, park, merge-go-check, rules, request, decide. A wait that runs out parks the lane. |
| Push a finished lane and open its PR | `lanes.py publish <stamp> --lane <x>` | Head only. Sons commit a branch and never push. Refused when the diff touches a protected path. |
| Approve one new lane under `dpp-full` | `lanes.py approve-lane <stamp> --lane <x>` | Needed when `dpp_full_ask_each_lane` is true. |
| Override a lane rule as the owner | `lanes.py override <lane> --reason ...` | Needs a human approval (`dts2_approvals`); refused in a son, a vote or the council. |
| Check whether the base is green before merging | `lanes.py base-health <stamp>`, `merge-mutex` | `merge-go` and `merge-go-step` refuse on a red base or while another lane holds the mutex. |
| Cap a post-merge fix | `lanes.py fix-attempt <stamp> --lane <x> --reason ...` | After `post_merge_fix_attempts` it opens one revert PR. |
| Close PRs a fold replaced | `lanes.py fold-close <stamp>` | After `fold --apply <group> --pr <n>`. |
| Run the whole backlog unattended | `fullauto` | `dpp-full` with autopilot forced on, looping check-in until `lanes.py stop-check` says nothing is outstanding. User-typed only. Budget caps in `.harness/config.yaml` bound it. |
| Open a PR for the branch you are on | `ship [base]` | Pre-check, repo checks, secret scan, verifier and reviewer, receipt, push, PR. Never merges. Then sweeps stale branches and PRs. Base defaults to `dev` when it exists. |
| See progress against the end state | `check-in` | Read-only checklist, `N of M complete`. |
| See what needs a person | `action-items`, `action-items done <id>`, `add`, `assign` | Secrets, decisions, handoffs, deploy steps, promotions. |
| Turn findings into lessons | `learn`, `learn promote <L-NNN>` | Prunes stale lessons only after the user approves the drops. |
| Change the harness itself | `evolve`, `evolve deploy` | Only in the harness source repo. Edit, validate, test, bump, commit; pushes only on an explicit yes. |
| Pick which provider leads | `model` | Lead, advisory and sign-off seats. Builders always run the cheapest capable model. |
| Find skills the repo could use | `find-skills` | Rescan, one to three questions, ranked suggestions, keep list on a yes. |
| Decide whether to keep, fold, sell, archive or delete one repo | `ask-expert [repo]` | Runs before setup. Asks your goal in plain words, reads the code, compares it with your active repos, then an expert panel (three providers; council and research if it stalls) writes a one-page memo. Changes nothing. |
| Do that for all your repos | `repo-sweep [owner]` | Quick pass per repo, oldest first, then one cleanup screen. Archive is reversible; delete is one repo at a time after a backup bundle and a typed repo name. |
| Go-to-market pass | `gtm` | Installs `marketing-skills` if missing, ends in `readiness.md`. |
| Run the pipeline headless (CI, cron, servers) | `sdk` | Sets up and runs `sdk/dts2-run.py` with the Agent SDK. User-typed only. |

Decision shortcuts:

- Not set up yet: `setup`. Everything else refuses or asks for it.
- One task, you want to watch: `run`. You do not want to watch: `autopilot`.
- More than one independent step and the lanes do not share files: `dpp`. They do share files: `autopilot` with the steps in order, or let `dpp` route the shared files to its integration lane.
- Only a PR, no build: `ship`. Only a plan, no PR of code: `feature`.
- Something is stuck: `check-in` first, then `action-items`, then `run resume` or `autopilot resume`.
- Never run `dpp`, `setup` or `onboard` inside a son (section 3).

### When a model runs out of usage

Usage limits belong to the account, so the harness keeps one shared list of paused agents (`~/.dts2/agent-status.json`).

- The first agent that hits a limit is recorded automatically. If the message carries no reset date, the harness asks you once and uses a five-hour pause until you answer.
- A paused agent is skipped by the roster probe and by lead failover, and is never re-probed; it comes back by itself when the time passes.
- Each new session starts with a one-line note of who is paused and until when.
- Set or lift a pause by hand with `/dts2:cooldown set <agent> <date or duration>`, `clear <agent>` and `list`.

### Personal knowledge across devices

`/dts2:knowledge` keeps your own standing preferences ("my standard team is 6 agents"), glossary terms (a brand and the repos in it) and cross-project lessons in a private store that is never part of the plugin.

- First time (once per person): `/dts2:knowledge setup` asks where it should live (cloud: a private GitHub repo, the default; a Cloudflare Worker + D1 that also works from claude.ai web and phone; or a OneDrive/Google Drive/Dropbox folder. Or this machine only) and an owner label. Each new computer: `/dts2:knowledge join`. Sign-in comes from `gh`/git or the drive app; no API keys are asked for or stored. The Cloudflare choice is the one exception to "no token": you deploy `templates/knowledge-cloudflare/` with wrangler, set its `KNOWLEDGE_TOKEN` secret, and export the same value as `DTS2_KNOWLEDGE_TOKEN` on each device. The token lives only in your environment, never in the store or the profile. The claude.ai custom connector form may insist on OAuth, which the template does not do yet (see its README).
- Use plain phrases: "remember my standard is 6 agents" (set), "what is acme" (get), "anything about releases" (find), "sync my knowledge" (sync).
- `/dts2:setup` reads it, shows what matches the repo, and asks before applying a preference such as the agent count.
- Nothing else reads it: no hook, no other skill.
- Do not store secrets; the script refuses tokens, passwords and keys.
- It is separate from cooldowns: those are live per-account state and do not go through git.

## 3. The head, son and council flow

Three roles appear in 3.10.0 and the words are used consistently across the skills.

**Head.** The Claude session that runs `dpp` (or a single `autopilot`). It is the only process that plans lanes, grants merges and talks to the user. Its sequence in `dpp`:

1. `lanes.py plan --from-checkin --draft` turns outstanding check-in items into a lane manifest (`lanes.json`): one lane per disjoint file set, each with a spend estimate, `provides`/`consumes` contracts and a merge order; `lanes.py check` validates overlap and the plan graph; lockfiles, migrations, route tables and barrel files go to a final integration lane.
2. Approval: the user under `dpp`, the three-provider vote under `autopilot`.
3. `lanes.py preflight` pins the `claude` version and tests a real son launch; `lanes.py lease --lane <x> --epoch <n>` takes a lease per lane; `lanes.py spawn --lane <x> --worktree <dir>` starts the son with every cap (`--max-turns`, `--max-budget-usd`, fallback models, sandbox, tool allowlist, allowlisted environment).
4. Supervise: `lanes.py status <stamp>` (stall marks past `builder_timeout_min`), `lanes.py sendback` (at most two per lane), `lanes.py transition` (the one writer of a lane's phase), and head-answered questions from `questions/<n>.md`. A son's question never reaches the user.
5. Merge in order: `lanes.py merge-order`, then per lane `lanes.py merge-go --lane <x> --head <sha>` (refused when the branch touched files outside its owned set; `lanes.py audit` explains why), `gh pr merge` through the merge guard, `lanes.py merge-done`. Target is `merge.target` (default `dev`); the default branch needs `merge-target --yes-default-branch`.
6. Fold: `lanes.py fold` groups blocked lanes into the fewest PRs; lessons and action items fold back; `dpp-report.md` (`lanes.py report-check`) and `task-ledger.py` close the run; `lanes.py shutdown` ends it gracefully.

**Son.** One headless `autopilot --son <stamp>/<lane>` per lane, launched by the head in the lane's worktree on branch `dts2/<stamp>/lane-<x>`. It reads `.harness/runs/<stamp>/<lane>/brief.md` first (about 4 KB: lane id, lease epoch, branch, file set, task list, `MAX_BUNDLE`). A son:

- builds in its own file set only, with builder branches `dts2/<stamp>/lane-<x>-b<n>`;
- heartbeats every turn (`lanes.py heartbeat <stamp> --lane <x>`) and records each builder step (`lanes.py builder`);
- may report only `pr-open`, `done`, `blocked` or `incomplete`, and stops at `pr-open`: the head publishes (push, PR) with `lanes.py publish` and merges;
- never merges, never runs `merge-go`, `reconcile`, `dpp`, `setup`, `onboard`, never starts another son, never writes `lessons.md` (lessons go in its `report.md`);
- asks the head, not the user, through the mailbox (`questions/<n>.json`); user prompts become need-human;
- runs without `GH_TOKEN`, `GITHUB_TOKEN`, `SSH_AUTH_SOCK` or cloud credentials unless `DTS2_SON_ENV_PASS` names them, under `guard.py --mode son` as the deny hook.

**Council.** Sits only when three full rounds of the autopilot gate fail (`council.py eligible`). Five frontier seats across as many providers as are usable (`council.py seats`); each reads the full dossier of the step and votes; ballots are fenced (`council.py wrap`), blind (`council.py blind` strips authorship and shuffles options), and a seat that times out is swapped (`seat_swap.py`). Every dissenting seat writes a brief. Fable 5.1 heads the council and decides: more fixes (at most two rounds), strike items (each becomes a Decisions action item) or approve, and its record must answer every dissent. The council is written to `.harness/council.md` and summarised in the PR, the receipt and `check-in`. One council per step; it never overrides a hard stop or branch protection.

**Gate before any vote.** `checks.py` runs tests, typecheck, lint, a secret scan and a scope check and writes each to `.harness/runs/<stamp>/ledger.jsonl`; `checks.py gate` and `council.py route` act on that ledger. A red check is never voted on.

## 4. Rules every agent follows

- `.harness/discipline.md` (Rule 8): follow the harness, do not improvise around it. The lead reads it first.
- `lanes.py` is the only writer of lane state; never edit `.harness/runs/<stamp>/` by hand.
- `merge-go.md` naming the head and base commits is the only thing that lets `gh pr merge` or a push to a protected branch through the merge guard (`hooks/merge-guard.sh`). Force-push is always refused. Denials land in `.harness/merge-guard.log`.
- Branch names: `dts2/<stamp>/main`, `main-b<n>`, `lane-<x>`, `lane-<x>-b<n>`, `step-<step>`. Never nested; git 2.38 or newer.
- Builders run the cheapest capable model at a complexity-scaled effort (`delegate.py` owns the policy; mechanical sections dispatch `haiku, low`). Frontier models sit only in advisory, review, sign-off and council seats.
- One PR bundles at most 5 tasks. A reviewer never edits; a verifier never fixes; a builder never reviews its own work; `fixer` takes fix round 2 with an escalation seat.
- Every model call outside the Agent tool goes through `model_call.py` (machine-wide call cap, 429 backoff, strict JSON).
- Companion skills pinned in `.harness/keep.yaml` with `pin: <sha>` are never updated without `--fix --apply-update NAME=SHA` after an explicit yes.
- Secrets never go in chat, logs or action items: logs and items are redacted, missing env vars are recorded by name only.

## 5. Release history

How to read the changelogs: `../CHANGELOG.md` holds every released version (open the `## [3.11.0]` or `## [3.10.0]` section), the `## Unreleased` section of `../README.md` holds work not yet released, and `../changelog.d/` holds one fragment per batch that the release step joins into those files. `COMMANDS.md` section 8 says how to read a section.

### 3.11.0

Full notes: `../CHANGELOG.md` section `[3.11.0]`; per-command detail: `INVENTORY.md` section 9.

- Head policy gate: `hooks/policy-gate.sh` and `templates/policy.json` deny force-push, `--admin`, deploy CLIs, `gh secret`, `vercel env` and a bare `env` for the head and every son; merges need a human approval.
- Son containment: the head pushes, opens and merges son PRs (`lanes.py publish`, `head_publish.py`); protected paths; human-only approvals in `.claude/settings.local.json` (`dts2_approvals`); allowlisted provider environment; council ballots carry a `.dispatch.json` record.
- Son lifecycle and mailbox: own process group, `son.json` and `exit.json`, stuck-loop detection, `lanes.py wait`, `gc`, `reconcile`, versioned `status.json` with epochs, the head/son mailbox with deadlines.
- Scope policy: `override`, `dpp_full_ask_each_lane`, `fullauto_freeze_scope`, lease holds a check-in item, `max_fullauto_loops: 3` stays a resumable park.
- Merge safety: base health and merge mutex gate `merge-go` and `merge-go-step`; `fix-attempt` and the revert PR; `fold-close`; integration routing records.
- Agent gates: retryable council dispatch failures, least-privilege agent tools, `subagent-stop.sh`, `stop-failure.sh`, `permission-denied.sh`.
- Hooks: every hook runs `python3 -I`; one shared Stop deadline; `stop_checks_block`, `context_guard_stop`, `pr_receipt_template_push`.
- Evals and skills: A/B mode in `evals/run.py` with `eval_stats.py`, pinned `skills` CLI, version-skew check (`harness_skew.py`).
- Reports and receipts: run-wide report sections, doctor rows for bwrap, socat, auth and platform, `receipts_sign.py`, `plugin_options.py`, `OTEL_` env allowlist.

### 3.10.0

Full notes: `../CHANGELOG.md` section `[3.10.0]`; per-command detail: `INVENTORY.md` section 7.

New commands and surfaces:

- Lane lifecycle in `lanes.py`: `transition`, `heartbeat`, `budget`, `merge-order`, `merge-go`, `merge-done`, `shutdown`, `reconcile`, `merge-resume`, `fold-done`, `walkthrough-failed`, `run-record`, `builder`, `run-resume`, `amend`, `merge-plan`, `merge-go-step`, `loop`, `preflight`, `spawn`, `call`, `merge-target`, `gc-restore`, `audit`, `report` (35 subcommands in all). `dpp`, `autopilot` and `fullauto` call them instead of describing the steps.
- Merge journal (`merge-journal.jsonl`), typed `run.json`, `builders.jsonl`; leases with TTL, heartbeat renewal and epochs.
- Son containment: sandbox, tool allowlist and deny list, allowlisted environment, pinned CLI version, hard caps on turns, spend and model calls, `--fallback-model` chain, per-lane `PORT`, `COMPOSE_PROJECT_NAME`, `DTS2_DB_NAME`.
- Merge guard hook and `guard.py`; `merge.target` default `dev`.
- Council hardening: seat swap, identical-round note, blind ballots, fenced ballots, strict verdict line, model ids per provider in `profiles/agents/<provider>.json`.
- Checks gate (`checks.py`) before any vote; verifier split into evidence scout plus frontier verifier.
- Plan gate (`plan-gate.py`, PLAN GATE PASS or FAIL), builder audit, mandatory `## Foundation` section at wave 0, `fixer` agent, fixed `FLAGS:` block, `rollback_ref.py`.
- State port (`state_io.py`, `state_ids.py`), `proc.py` runners, `mdparse.py`, `contracts.py`, `profiles.py`.
- Lessons with path globs, 90-day pruning, regression tracking; PreCompact handoff refresh; SubagentStop report contracts; one-page lead brief and ~4 KB son brief.
- Production readiness: `prod-scaffold.py` (CI, `RUNBOOK.md`, `ops/`), `app-type-detect.py`, Production readiness table in `end-state.md`, Dependabot or Renovate offer in `setup`.
- Tooling: `run_report.py`, `run_metrics.py`, `walkthrough_fallback.py`, `bump-version.py`, `make test`, `make doctor`, `make check-version`, `evals/run.py`, Hypothesis property tests, CI on Python 3.10 to 3.13.
- Docs: `docs/INVENTORY.md` with a completeness test, `ARCHITECTURE.md`, this guide.

Behaviour that changed:

- `run`, `autopilot` and `setup` are short routers plus phase files read on demand.
- Branch names no longer nest (section 4).
- `lanes.py lease` and `plan` fail closed without `gh` (`--no-prs` opts out).
- Skill and agent descriptions are cut to about 250 characters; `context-tax.py` fails above 6000 tokens; six skills are user-typed only.
- `npx skills update` never runs; skill updates are proposals in `.harness/skill-updates.json`.
- Sons have no GitHub token, SSH agent or cloud credentials by default.
- Exit 143 from a seat is a `timeout` the council can swap.

Release history before 3.10: 3.9 parallel autopilot (`dpp`, `dpp-full`, `fullauto`); 3.8 autopilot council; 3.7 pre-check, `ship`, `feature`, `autopilot`; 3.6 strict delegation, `model`, `find-skills`, `check-in`; 3.5 `muse` on the roster; 3.0 end-state interview, checkpoints, roster, `action-items`, `learn`, `gtm`, `machine-prep`, `evolve`.

## 6. Where state lives

| Path | Holds | Written by |
|---|---|---|
| `.harness/end-state.md` | The approved end state, sections numbered, Production readiness table | `setup`, `feature` |
| `.harness/config.yaml` | `budget:`, `council:`, `merge.target`, `lanes.shared_files`, timeouts | `setup`, the user |
| `.harness/keep.yaml` | Companion skills, optional `pin:` | `setup`, `find-skills` |
| `.harness/lessons.md` | Lessons every run reads | `learn` (sons report instead) |
| `.harness/state.md`, `.harness/handoff/latest.md` | Current state and the resume pointer | `run`, hooks (PreCompact, SessionEnd) |
| `.harness/action-items.md` | Secrets, Decisions, Handoff, Deploy, Promotions | `action-items.py` |
| `.harness/receipts/<stamp>.md` | Ship receipts | `run`, `ship`, `autopilot` |
| `.harness/ask-expert/<repo>/` | Goal answers, `goal.json`, comparison, panel record, research, `report.md`; `sweep-<stamp>.jsonl` and `todo.md` beside them | `ask-expert`, `repo-sweep`, `ask_expert.py` |
| `~/.dts2/repo-backups/` | `git bundle` backups written before any repo delete (outside the repo) | `ask_expert.py backup` |
| `.harness/council.md` | Every council vote, dissent and decision | `council.py ledger` |
| `.harness/runs/<stamp>/` | `lanes.json`, `run.json`, `builders.jsonl`, `ledger.jsonl`, `merge-journal.jsonl`, `merge-go.md`, per-lane `brief.md`, `report.md`, `questions/` | `lanes.py`, `checks.py` only |
| `.harness/merge-guard.log` | Refused merges and pushes | `guard.py` |
| `.harness/cache` | Shared build cache across lanes | sons |

`.harness/runs/`, receipts and review receipts are never committed; `ensure-ignored.py` keeps them out of git.
