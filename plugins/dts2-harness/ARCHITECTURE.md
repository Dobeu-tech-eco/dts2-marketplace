# dts2-harness architecture

One page. It describes what exists in this plugin: the skills that drive a run, the agents they dispatch, the scripts that hold the rules, the state under `.harness/`, and the hooks. Rules live in `templates/discipline.md` and the skills; this page only maps them.

## Flow

```mermaid
flowchart TD
  user([Approved end state]) --> run["run skill: preflight, pre-check"]
  run --> scout["scout: size and budget"]
  scout --> lead["lead: plan, file sets, done criteria"]
  lead --> cp1{{Plan checkpoint}}
  cp1 --> builders["builders: parallel, one file set each"]
  builders --> gate["checks.py: tests, types, lint, secret scan"]
  gate --> reviewers["reviewers: one per axis"]
  reviewers --> verifier["verifier: evidence, no fixes"]
  verifier --> cp2{{Ship checkpoint}}
  cp2 --> ship["ship: receipt, PR"]

  autopilot["autopilot: council.py votes replace both checkpoints"] -.-> cp1
  autopilot -.-> cp2
  dpp["dpp head: lanes.py plan, lease, spawn"] --> lane1["lane: autopilot son in its own worktree"]
  dpp --> lane2["lane: autopilot son in its own worktree"]
  lane1 --> run
  lane2 --> run
  dpp --> merge["lanes.py merge-order, merge-go: one merge at a time"]
```

- **run** is the pipeline: preflight, scout (tier and builder count), lead (plan), builders, review and verify, ship. A human approves at the Plan and Ship checkpoints.
- **autopilot** replaces those two human checkpoints with a vote. The ballots are tallied by `scripts/council.py`; after three unsettled rounds the council sits, a dissenter must write a brief, and the head of the council answers each one.
- **dpp** (and **fullauto**, which loops it) runs several autopilot lanes at once. Each lane is a headless son in its own worktree and branch (`dts2/<stamp>/lane-<id>`). `scripts/lanes.py` is the only writer of lane state: file-set overlap check, leases with epochs, spawn under spend and model-call caps, heartbeats, send-backs, merge order.
- **ship** pushes the branch and opens the PR with the change receipt.

## Agents

| Agent | Role |
| --- | --- |
| scout | read-only sizing, harness and marketing-surface detection, evidence collection |
| lead | read-only planner; slices the end state into builder sections with exclusive file ownership |
| builder | implements one builder section inside its file set |
| fixer | fresh-context fixer for fix round 2 on the same failure; applies the one hypothesis the lead picked (escalation seat, `effort: high`) |
| reviewer | read-only review on one or all axes; severity-rated findings and a verdict |
| verifier | read-only; runs the configured commands and reports evidence |
| auditor | read-only inventory of installed agent tooling (used by machine-prep) |

## State under `.harness/`

| Path | Written by | Holds |
| --- | --- | --- |
| `config.yaml`, `review-checklist.md`, `discipline.md`, `keep.yaml` | setup | commands, roster, review checklist, rules copy, keep list |
| `end-state.md`, `state.md`, `lessons.md`, `action-items.md` | setup, run, learn, action-items | approved end state, progress, lessons, open items |
| `handoff/latest.md`, `handoff/<agent>/<n>.md` | `handoff-write.py`, stop hook | resume point for any agent |
| `runs/<stamp>/plan.md`, `receipt.md`, `task-ledger.md` | run, ship, `task-ledger.py` | plan, change receipt, per-task record |
| `runs/<stamp>/ledger.jsonl` | `checks.py`, `council.py` | check results with HEAD sha, env, ballots |
| `runs/<stamp>/run.json`, `budget.json`, `model-ledger.jsonl` | `lanes.py` | typed run record (CLI version pin, kind), spend counter, model-call ledger |
| `runs/<stamp>/flags.md` | `flags_collect.py` | the builders' `FLAGS:` blocks, one section per builder |
| `runs/<stamp>/merge-order.json`, `merge-go.md`, `merge-journal.jsonl` | `lanes.py` | serialised merge state; journal of grants, merges, fold groups and failed walkthroughs |
| `runs/<stamp>/builders.jsonl` | `lanes.py` | one event row per builder step (section, branch, status, diff-confirmed sha, round) for `run resume` |
| `runs/<stamp>/<lane>/lease.json`, `status.json`, `brief.md`, `send-back-<n>.md`, `questions/<n>.md` | `lanes.py`, the son | lane lease and epoch, phase and heartbeat, brief, send-backs, son questions |
| `autopilot/latest.md`, `council.md` | autopilot, `council.py` | last autopilot run, council decisions |
| `metrics.jsonl` | `metrics.py`, `run_metrics.py` | one line per run for the trend report |
| `wt/<n>/` | run | scratch directories for builders when the folder is not a git repo |

State reads and writes from the scripts go through `scripts/state_io.py`; see "State port" below.

## Hooks

| Event | Script | What it does |
| --- | --- | --- |
| SessionStart | `hooks/session-lessons.sh` | puts recent lessons, open state items and open action items into context; after a compact (`source` is `compact`) prints only a short resume pointer |
| PreCompact (auto, manual) | `hooks/pre-compact.sh` | runs `handoff-write.py` so the post-compact session resumes from the handoff |
| Stop | `hooks/stop-checks.sh` | refreshes `handoff/latest.md`, runs quick typecheck and lint on changed files; warns, never blocks |
| PreToolUse (Bash) | `hooks/merge-guard.sh` | refuses a force-push, and a merge or push to a protected branch unless a lane's `merge-go.md` allows it |
| PostToolUse (Bash, `gh pr create *` and `gh pr edit *`) | `hooks/pr-receipt.sh` | on `gh pr create` or `edit`, makes sure the PR body carries the change receipt |
| PostToolUse (Bash, Edit, Write, Agent) | `hooks/context-guard.sh` | stops a run on a context spike before the plan checkpoint |
| SubagentStop (builder, reviewer, verifier) | `hooks/subagent-report.sh stop` | checks the final report for its required `## ` sections with `contracts.parse_report` (`scripts/subagent_report.py`); blocks once, naming the missing sections; skips when `stop_hook_active`; a turn-cap partial report passes |
| PostToolUse (SubagentHandback) | `hooks/subagent-report.sh handback` | the same check for agents that finish through `SubagentHandback`, on `tool_input.message`; blocks once per agent |
| SessionEnd (logout, prompt_input_exit, other) | `hooks/session-end.sh` | releases only the leases stamped with this session's id (`scripts/session_end.py`, through `state_io`), then runs `handoff-write.py`; best effort, lease expiry is the guarantee |
| PreToolUse (Bash `lanes.py spawn --dry-run`, Agent) | `hooks/spawn-dry-run.sh` | prints the exact son command, env names, byte counts and the son `brief.md` (`scripts/spawn_dry_run.py`, on `briefs.dry_run`) and refuses the call so nothing starts; for Agent only when `spawn_dry_run: true` |

Hooks read settings from `.claude/dts2-harness.local.md` through `hooks/lib-settings.sh`.

## State port

`scripts/state_io.py` is the one module that knows where the files under `.harness/` live and the one writer of them. A test (`tests/test_b12_g8.py`) fails when another script holds a `.harness/` path as a code string; the only exceptions are `lanes.py`, `ensure-ignored.py` (gitignore patterns) and `harness-lock.py` (names of protected records).

- **Layout.** Path constants (`CONFIG_REL`, `STATE_MD_REL`, `ACTION_ITEMS_REL`, `HANDOFF_LATEST_REL`, `METRICS_REL`, `RUNS_REL`, `CACHE_REL`, `MODEL_SLOTS_REL` and the rest) and builders `rel`, `run_rel(stamp, ...)`, `lane_rel(stamp, lane, ...)` and `harness_path(repo, ...)`. The run directory is `runs/<stamp>/`; a lane's is `runs/<stamp>/<lane>/`, holding `lease.json`, `status.json`, `brief.md`, `send-back-<n>.md` and `questions/`.
- **Identity.** `scripts/state_ids.py` holds `Stamp` and `LaneId`; `run_rel` and `lane_rel` accept only those (or strings that parse), so no path can be `runs/None/` or climb out with `..`.
- **Writes.** `atomic_write` (temp file, fsync, `os.replace`, directory fsync, file mode kept) and `append_text` (`O_APPEND`; a header is written together with the first row). A crash leaves the old file or the new one.
- **Store.** `Store` is the interface; `FileStore` is the disk and `MemoryStore` the in-memory fake the tests use. `State` is the typed layer on top: leases, status, send-backs, ledger rows and events.
- **Locks.** `Store.lock` takes `<path>.lock`; a stale lock is reclaimed by rename under a reclaim guard, a holder can `renew()`, and a reclaimed holder never frees its successor's lock.
- **Epochs.** `State.acquire_lease` and `release_lease` require `epoch=` (`EpochRequired`, `StaleEpoch`); a send-back number is taken by exclusive create, so racing callers never share one.
- **Versions.** Records carry `"v": 1`. `migrate()` upgrades through a per-kind table and refuses a newer version; `state_io.py migrate-all [repo]` upgrades a whole `runs/` tree and is safe to repeat.
- **Events.** Ledger, merge-journal and metrics rows share one shape `{v, ts, run, lane, kind, id}` (`make_event`, `State.append_event`). A row written with a caller-chosen `event_id(...)` is recorded once, so a re-run does not duplicate ballots or a metrics stamp.

Settings are read by `scripts/miniyaml.py` (one parser for `config.yaml`, `keep.yaml` and the local frontmatter) and cached by `scripts/settings_cache.py`.

## Lane tools

`scripts/lanes.py` is a thin argparse CLI (35 subcommands, JSON on stdout) over the `scripts/lanes/` package. It is the only writer of lane state; the head and the sons call it and never edit those files. Dependencies point down this table: `common` and `records` are imported by almost everything, `phases` and `merge` by the lifecycle modules.

| Module | Responsibility |
| --- | --- |
| `scripts/lanes/common.py` | constants (phase names, `HEARTBEAT_PHASES`, `COST_SOURCES`, `LANE_SECTIONS`), `LaneError`, `load_manifest` |
| `scripts/lanes/records.py` | locked reads and writes of one JSON object through the state port, the model-call ledger; knows nothing of a lane's lifecycle |
| `scripts/lanes/conflicts.py` | overlap detection between lanes (file, schema, id, dependency, area, scope) and the open-PR and active-run sources |
| `scripts/lanes/integration.py` | routes lockfiles, migrations, route tables, barrels and `lanes.shared_files` globs to a final integration lane; caps a PR at 5 tasks |
| `scripts/lanes/gitrefs.py` | branch names (`dts2/<stamp>/lane-<id>`) and the collision check against existing refs |
| `scripts/lanes/leases.py` | lane leases: epoch fence, expiry (`expires_at`, `ttl_s` of twice `max_wall_minutes`), `renew_lease`, and the overlap check plus lease write under one admission lock |
| `scripts/lanes/planner.py` | the son command line, admission, spend estimates and the `plan` command |
| `scripts/lanes/amend.py` | `amend`: change one lane of a running manifest, re-check, bump the epoch, rewrite `brief.md` |
| `scripts/lanes/runstate.py` | status and stall marks, send-backs, `fold` groups, `stop-check`, `report-check`, the budget counter and spend ledger |
| `scripts/lanes/supervisor.py` | `preflight`, `spawn` and the son lifecycle, `model_call`, `loop`, `gc_restore` (see below) |
| `scripts/lanes/phases.py` | `transition`, the one writer of a lane's phase, with its `LEGAL` table |
| `scripts/lanes/shutdown.py` | graceful end of a run |
| `scripts/lanes/reconcile.py` | ask GitHub before creating, merging or resuming; orphan handling |
| `scripts/lanes/runrecord.py` | the typed `run.json` (`RunRecord`) and `builders.jsonl` rows |
| `scripts/lanes/merge.py` | merge order, merge target, `merge-go` grants, `merge-done` |
| `scripts/lanes/mergeplan.py` | merge queue or serial rebase-test-merge plan with the `git merge-tree --write-tree` probe |
| `scripts/lanes/journal.py` | `merge-journal.jsonl`: grants, merges, fold plans, shipped fold groups, failed walkthroughs and the one revert action item |
| `scripts/lanes/mergeresume.py` | settle a merge a dead head left half done, by asking GitHub |
| `scripts/lanes/runend.py` | run metrics at the end of a run (`run_metrics.py` hooks) and the run report view |

## Plan graph and briefs

`scripts/plan_graph.py` is the graph layer over a lane manifest. `lanes.py check`, `lease` and `plan` call `graph_check`, `graph_lease` and `annotate_plan` in-process, so the three gates agree; `plan_graph.py analyse`, `merge-order` and `brief` run it by hand.

- Contracts: `provides`, `consumes` and `stubbed_on` names. A plain consumer waits for its provider; a stubbed consumer starts at once and merges after its provider. `merge-order` records the provider-first order that `merge-go` then follows.
- Owners may be exact files, `dir/` prefixes or globs; overlaps between them are caught, empty and repo-wide owners are refused, and a package manifest owns the lockfile beside it.
- Areas come from package roots, so vertical slices of one package do not serialise; three single-layer lanes get a slice-by-feature warning.
- A cycle check and the critical-path line are part of the `plan` result; `brief` prints the six-section lane brief for the lead.

`scripts/briefs.py` builds what a model reads and starts nothing: `son-brief` fills `templates/son-brief.md` (the ~4 KB `brief.md` a son reads first), `lead-brief` turns the task, roster, probe and check ledger into one page for the lead, `prefix` is the fixed-order cached prefix (discipline, roster, probe) that `son_launch.launch_flags` passes every son with `--append-system-prompt`, and `dry-run` prints the exact son command, env names and byte counts.

## Supervisor and lifecycle

- **Launch.** `lanes.py preflight` pins `claude --version` in `run.json` and tests the real son launch; `spawn` refuses a different version, a missing preflight, a lane whose recorded pids are alive, and a second unattended son while the sandbox is off. `scripts/son_launch.py` supplies the environment allowlist, per-lane `PORT`, `COMPOSE_PROJECT_NAME` and `DTS2_DB_NAME`, the settings JSON (deny hook, sandbox block) and the tool lists; the deny list itself is `guard.py --mode son`.
- **Calls.** `scripts/model_call.py` is the one door for headless model calls (shared concurrency limit by flock slots, wall-clock kill, backoff on 429, strict parsing of the JSON result); it never writes state, `lanes.py` records its events. `scripts/proc.py` is the one place child processes start (`Runner` with real, fake and dry-run implementations; exit 143 on timeout).
- **Budget.** `runstate` keeps the spend counter and per-lane shares; `spawn` and `call` refuse once the budget caps are spent, and every model call shares one machine-wide limit (`supervisor.max_model_calls`).
- **Phases.** `scripts/lanes/phases.py` `transition` is the only code that changes `status` in `status.json`. The phases are starting, pr-open, done, blocked, incomplete and orphaned; `LEGAL` maps each to the moves it allows (done allows none), `starting` and `orphaned` are the head's moves, and a son may report only pr-open, done, blocked or incomplete. `heartbeat --status`, parking, stall marks and `spawn` all go through it, and each move renews the lease and writes a ledger line.
- **Shutdown.** `shutdown` parks running lanes (reason `shutdown`), sends SIGTERM to each son's process group and SIGKILL after a 10 s grace, closes leases, returns budget shares and restores `gc.auto`.
- **Reconcile.** `reconcile` reads the PRs for each lane's branch and returns one action per lane: `merged`, `adopt-pr`, `create-pr`, `resume`, `park`, `stalled` or `none`. An orphaned lane (quiet, no running process, dirty worktree, no report, no PR) gets one resume and is then parked. Without `gh` it fails closed.
- **Run record.** `runrecord` types `run.json` for dpp and autopilot runs alike and rejects a wrong-typed field before writing; `builder` rows confirm the reported sha against the branch tip and diff, and `run-resume` reads both so resume parses no Markdown.
- **Merge.** `merge-plan` chooses the mode, `merge-go` writes `merge-go.md` for one head and base commit (head only), `merge-done` releases the turn, `journal` records every step, and `merge-resume` finishes a merge a dead head left open.

At 3.10.0 the lifecycle commands (`transition`, `shutdown`, `reconcile`, `run-record`, `builder`, `run-resume`, `fold-done`, `merge-resume`, `walkthrough-failed`, `report`) exist in the CLI but no skill text calls them yet; `docs/INVENTORY.md` marks them.

## Scripts by job

| Job | Scripts |
| --- | --- |
| Deterministic gate | `checks.py` (tests, types, lint, secret scan, scope; run ledger), `plan-gate.py` (PASS or FAIL for a lead plan), `builder-audit.py` over `ownership_audit.py` (empty diff with DONE, file outside the owned set, claimed commit not HEAD), `flags_collect.py` (`FLAGS:` blocks into `runs/<stamp>/flags.md`) |
| Review | `findings.py` (severity calibrated by the `DIMENSIONS` table, deduped by file:line, digest for the final reviewer), `review_split.py` (path-group slices above a line threshold), `rollback_ref.py` (`refs/dts2/<stamp>/base` and the human-run Rollback line) |
| Council | `council.py` (dossier, tally, route, blind ballots, seats, wrap), `seat_swap.py` (swap a timed-out seat for the next bench provider; note identical findings in the run ledger) |
| Roster | `roster.py`, `delegate.py`, `failover.py`, `profiles.py` (which agent and model for which seat) |
| Contracts | `mdparse.py` (one Markdown tokenizer), `contracts.py` (parsers for vote entry, ballot, decision, sections, acceptance, report: a dataclass or `Invalid`) |
| Metrics and reports | `metrics.py`, `run_metrics.py` (lanes, tokens, wall-clock; plan-time and post-run warnings), `run_report.py` (one run as a markdown table) |
| Project and setup | `prod-scaffold.py`, `app-type-detect.py`, `deploy-detect.py`, `repo-size.py`, `doctor.py` (`make doctor`), `walkthrough_fallback.py` (optional Playwright post-merge walkthrough: sandbox only, host allowlist, no `file://`) |
| Release | `bump-version.py`, `changelog-join.py`, `context-tax.py` |

`skills/autopilot/`, `skills/run/` and `skills/setup/` are a short router (`SKILL.md`) plus phase files read on demand (`phase-*.md`, `son-mode.md`, `modes.md`, `operations.md`); a son reads its brief and `son-mode.md` first.

Hook entry points (each is called by one `hooks/*.sh`, reads the hook JSON on stdin, exits 0): `subagent_report.py`, `session_end.py`, `spawn_dry_run.py`, `context-guard.py`, `pr_payload.py`, and `guard.py` (`--mode merge` from `hooks/merge-guard.sh`; `--mode son` is wired into sons by `lanes.py spawn`).

## Library modules

Imported by the scripts above; none is a hook entry point.

| Module | Holds |
| --- | --- |
| `scripts/miniyaml.py` | the one reader for `.harness/config.yaml`, `keep.yaml` and the settings frontmatter; typed accessors with defaults |
| `scripts/_load.py` | loads a hyphenated CLI script by hyphenated or underscore name, cached in `sys.modules` |
| `scripts/settings_cache.py` | schema plus defaults for budget, supervisor and local settings, cached in `.harness/settings.cache.json` (gitignored, mode 600) |
| `scripts/profiles.py` | `Profiles`: loads `profiles/agents/*.json`, `model`, `token_burn`, `lead_eligible`; tests inject a dict |
| `scripts/state_io.py`, `scripts/state_ids.py` | the state port and the `Stamp` and `LaneId` value objects (see "State port") |
| `scripts/mdparse.py`, `scripts/contracts.py` | the Markdown tokenizer and the text-contract parsers on it |
| `scripts/proc.py` | child-process seam: `Runner` (real, fake, dry-run), timeout kill (143), 429 backoff, version pin and fallback flags; `model_call`, `skills-check` and `task-ledger` go through it |
| `scripts/model_call.py`, `scripts/son_launch.py` | the model-call door and the son launch settings (see "Supervisor and lifecycle") |
| `scripts/ownership_audit.py` | the shared `audit(diff, owned, claimed_sha)` core behind `builder-audit.py` |
| `scripts/skill_pins.py` | commit pins, update proposals and lock freshness for companion skills; pure functions used by `skills-check.py` |
