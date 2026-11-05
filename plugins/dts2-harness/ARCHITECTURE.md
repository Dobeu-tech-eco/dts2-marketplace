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
| `runs/<stamp>/run.json`, `budget.json`, `model-ledger.jsonl` | `lanes.py` | pinned CLI version, spend counter, model-call ledger |
| `runs/<stamp>/merge-order.json`, `merge-go.md` | `lanes.py` | serialised merge state |
| `runs/<stamp>/<lane>/lease.json`, `status.json`, `brief.md`, `send-back-<n>.md`, `questions/<n>.md` | `lanes.py`, the son | lane lease and epoch, phase and heartbeat, brief, send-backs, son questions |
| `autopilot/latest.md`, `council.md` | autopilot, `council.py` | last autopilot run, council decisions |
| `metrics.jsonl` | `metrics.py` | one line per run for the trend report |
| `wt/<n>/` | run | scratch directories for builders when the folder is not a git repo |

State writes from the scripts go through `scripts/state_io.py` (`atomic_write`, `append_text`).

## Hooks

| Event | Script | What it does |
| --- | --- | --- |
| SessionStart | `hooks/session-lessons.sh` | puts recent lessons, open state items and open action items into context |
| Stop | `hooks/stop-checks.sh` | refreshes `handoff/latest.md`, runs quick typecheck and lint on changed files; warns, never blocks |
| PreToolUse (Bash) | `hooks/merge-guard.sh` | refuses a force-push, and a merge or push to a protected branch unless a lane's `merge-go.md` allows it |
| PostToolUse (Bash) | `hooks/pr-receipt.sh` | on `gh pr create` or `edit`, makes sure the PR body carries the change receipt |
| PostToolUse (all tools) | `hooks/context-guard.sh` | stops a run on a context spike before the plan checkpoint |

Hooks read settings from `.claude/dts2-harness.local.md` through `hooks/lib-settings.sh`.

## Scripts worth knowing

`checks.py` (deterministic gate), `council.py` (dossier, tally, blind ballots, seats), `lanes.py` (lane leases and supervision), `roster.py` and `delegate.py` (which agent and model for which seat), `prod-scaffold.py` (CI and ops files for a target app), `doctor.py` (preflight table, `make doctor`), `repo-size.py` (tier, per-module lines, heavy files and suggested sections).

`ownership_audit.py` (the shared `audit(diff, owned, claimed_sha)` core) and `builder-audit.py` (its CLI: empty diff with DONE, file outside the owned set, claimed commit not HEAD).
