# dts2-harness 3.10 agent guide

How to talk to the harness, which command to reach for, and what changed in 3.10.0. Written for an agent (or a person) who lands in a repo that uses the harness and needs to act without reading every skill file. The exhaustive reference is `INVENTORY.md` (every skill, agent, hook, script and `lanes.py` subcommand); the internals are in `../ARCHITECTURE.md`; the full release notes are in `../CHANGELOG.md`.

Contents: 1 Talking to the harness, 2 Which command when, 3 The head, son and council flow, 4 Rules every agent follows, 5 What changed in 3.10.0, 6 Where state lives.

## 1. Talking to the harness

The harness is a Claude Code plugin. Every entry point is a slash command `/dts2-harness:<skill>`; there is no other interface. Eighteen skills exist (section 2). Seven agents (`lead`, `builder`, `fixer`, `reviewer`, `verifier`, `scout`, `auditor`) are dispatched by the skills, never typed by the user; an agent that needs one calls the Agent tool with `subagent_type: dts2-harness:<name>`.

Six skills run only when the user types them (`disable-model-invocation: true`): `dpp-full`, `fullauto`, `machine-prep`, `model`, `onboard`, `sdk`. The others may be invoked by the model when the conversation calls for them.

Install and update:

```
/plugin marketplace add Dobeu-tech-eco/dts2-marketplace
/plugin install dts2-harness@dts2
/plugin marketplace update dts2      # then /reload-plugins
```

Arguments go after the command name, separated by spaces. Quote a task that contains spaces. Examples:

```
/dts2-harness:run add rate limiting to the public API
/dts2-harness:run section 4
/dts2-harness:run resume
/dts2-harness:run add secret STRIPE_KEY
/dts2-harness:run review-pr 52
/dts2-harness:autopilot 3-5
/dts2-harness:autopilot feature "export orders to CSV"
/dts2-harness:autopilot --son 20261105T0412/lane-b
/dts2-harness:dpp dry-run
/dts2-harness:ship dev
/dts2-harness:feature "nightly report emailer"
/dts2-harness:action-items done S-3
/dts2-harness:learn promote L-012
```

Scripts are never typed by the user. Skills call them as `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" <subcommand> ...`; each prints one JSON object on stdout. `INVENTORY.md` section 4 lists every script and flag.

The harness answers in a fixed shape:

- A run ends with a receipt (`.harness/receipts/<stamp>.md`) and a PR link, or a parked state with the reason.
- A checkpoint is a question with the plan or the ship summary and the words `approve`, `edit` or `stop`. Under `run` the user answers; under `autopilot` three frontier providers vote and Fable 5.1 breaks a tie.
- Anything that needs a person is an action item (`/dts2-harness:action-items`): a missing secret, a decision, a handoff, a deploy step. The item names the command that resolves it.
- Progress is always readable without side effects: `/dts2-harness:check-in`.

## 2. Which command when

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
| Run the whole backlog unattended | `fullauto` | `dpp-full` with autopilot forced on, looping check-in until `lanes.py stop-check` says nothing is outstanding. User-typed only. Budget caps in `.harness/config.yaml` bound it. |
| Open a PR for the branch you are on | `ship [base]` | Pre-check, repo checks, secret scan, verifier and reviewer, receipt, push, PR. Never merges. Then sweeps stale branches and PRs. Base defaults to `dev` when it exists. |
| See progress against the end state | `check-in` | Read-only checklist, `N of M complete`. |
| See what needs a person | `action-items`, `action-items done <id>`, `add`, `assign` | Secrets, decisions, handoffs, deploy steps, promotions. |
| Turn findings into lessons | `learn`, `learn promote <L-NNN>` | Prunes stale lessons only after the user approves the drops. |
| Change the harness itself | `evolve`, `evolve deploy` | Only in the harness source repo. Edit, validate, test, bump, commit; pushes only on an explicit yes. |
| Pick which provider leads | `model` | Lead, advisory and sign-off seats. Builders always run the cheapest capable model. |
| Find skills the repo could use | `find-skills` | Rescan, one to three questions, ranked suggestions, keep list on a yes. |
| Go-to-market pass | `gtm` | Installs `marketing-skills` if missing, ends in `readiness.md`. |
| Run the pipeline headless (CI, cron, servers) | `sdk` | Sets up and runs `sdk/dts2-run.py` with the Agent SDK. User-typed only. |

Decision shortcuts:

- Not set up yet: `setup`. Everything else refuses or asks for it.
- One task, you want to watch: `run`. You do not want to watch: `autopilot`.
- More than one independent step and the lanes do not share files: `dpp`. They do share files: `autopilot` with the steps in order, or let `dpp` route the shared files to its integration lane.
- Only a PR, no build: `ship`. Only a plan, no PR of code: `feature`.
- Something is stuck: `check-in` first, then `action-items`, then `run resume` or `autopilot resume`.
- Never run `dpp`, `setup` or `onboard` inside a son (section 3).

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
- may report only `pr-open`, `done`, `blocked` or `incomplete`, and stops at `pr-open`: the head merges;
- never merges, never runs `merge-go`, `reconcile`, `dpp`, `setup`, `onboard`, never starts another son, never writes `lessons.md` (lessons go in its `report.md`);
- asks the head, not the user, through `questions/<n>.md`;
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

## 5. What changed in 3.10.0

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
| `.harness/council.md` | Every council vote, dissent and decision | `council.py ledger` |
| `.harness/runs/<stamp>/` | `lanes.json`, `run.json`, `builders.jsonl`, `ledger.jsonl`, `merge-journal.jsonl`, `merge-go.md`, per-lane `brief.md`, `report.md`, `questions/` | `lanes.py`, `checks.py` only |
| `.harness/merge-guard.log` | Refused merges and pushes | `guard.py` |
| `.harness/cache` | Shared build cache across lanes | sons |

`.harness/runs/`, receipts and review receipts are never committed; `ensure-ignored.py` keeps them out of git.
