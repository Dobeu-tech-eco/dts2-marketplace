# dts2-harness command reference

> Migrating from dts2-harness (old name): the plugin is now `dts2`, so commands are `/dts2:<command>`. Run `/plugin uninstall dts2-harness@dts2`, `/plugin marketplace update dts2`, `/plugin install dts2@dts2`, `/reload-plugins`; settings and `.harness/` state are unchanged.

The one page an agent (Claude Code, Codex, Cursor or any other) reads to learn every command in this plugin and exactly how to call it. It is built from the code: `scripts/lanes.py` and every `scripts/*.py` argparse definition, `skills/*/SKILL.md`, `agents/*.md` and `hooks/hooks.json`. For the reasons behind a command read `GUIDE.md`; for the long-form table of every command with its callers read `INVENTORY.md`; for internals read `../ARCHITECTURE.md`. What changed in each release is in the last section.

Contents: 1 How to run a command, 2 `lanes.py` subcommands, 3 Standalone scripts, 4 Skills (slash commands), 5 Agents, 6 Hooks, 7 Common flows, 8 Changelogs.

## 1. How to run a command

- Scripts: `python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/<name>.py" <args>`. `CLAUDE_PLUGIN_ROOT` is set inside Claude Code; from a shell, use the installed plugin path (the folder holding `scripts/`, `skills/` and `hooks/`). Every script prints one JSON object on stdout unless a row says otherwise. Exit codes: 0 ok, 1 a violation or refusal, 2 a failed result (`lanes.py`, `walkthrough_fallback.py`).
- `lanes.py` takes global flags before the subcommand: `--runs-dir DIR`, `--cwd DIR`, `--no-prs` (skip the open-PR check on purpose). Every `lanes.py` invocation below is written without the prefix `python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/lanes.py"`; add it. `<stamp>` is the run stamp, `<manifest>` the lane manifest `lanes.json` in the run folder (`.harness/runs/<stamp>/`), `a` a lane id.
- Skills are slash commands typed in Claude Code: `/dts2:<name> [args]`. Quote a task that has spaces.
- Agents are dispatched with the Agent tool, `subagent_type: dts2:<name>`. Hooks are run by Claude Code on events; an agent never calls a hook.
- Ask any script for its flags with `--help`; ask `lanes.py <subcommand> --help` for one subcommand.

**Roles.** The *head* is the Claude session that runs `dpp` (or a single `autopilot`): it plans lanes, grants merges, pushes and opens PRs, and is the only party that talks to the user. A *son* is a headless `autopilot --son <stamp>/<lane>` in its own worktree: it builds inside its owned files, commits a branch, heartbeats, asks the head through the mailbox, and never pushes, merges or starts another son. The Role column says who may run a command: `head`, `son`, `either`, `owner` (needs the human approval channel), `hook` (called by Claude Code, not by an agent), `user` (typed by a person), `maintainer` (release and repo upkeep).

**Role markers in the environment.** A process counts as a son when `DTS2_SON` is set (every son's environment carries it), when `DTS2_SON_BRANCH_PREFIX` is set, or when `DTS2_ROLE=son`. `DTS2_ROLE=vote`, `voter` or `council` marks a council voter. A son refuses the head-only commands (`lanes.py` returns `ok: false` and exit 2); a voter or council seat is also refused `publish`, and `override` is refused to a son, a vote and the council. Human approvals are the `dts2_approvals` key in `.claude/settings.local.json`, which no model can write; they are checked with `approvals.py`.

## 2. `lanes.py` subcommands (46)

`lanes.py` is the only writer of lane state (leases, `status.json`, the budget counter, the model-call ledger, merge order, merge journal). Never edit the run folder by hand. Every subcommand has a row in `INVENTORY.md` section 4.5.

| Command | Role | What it does | Exact invocation | Writes / side effects |
|---|---|---|---|---|
| `check` | head | Overlap check on a lane manifest plus the plan-graph checks (contracts, owners, cycles, critical path). Advisory. | `lanes.py check lanes.json` | none |
| `lease` | head | Take a lane lease. Fails closed without `gh` unless `--no-prs`; refuses a lane that `approve-lane` has not cleared when `dpp_full_ask_each_lane` is true. | `lanes.py lease lanes.json --lane a --epoch 1` | lease file in the run folder |
| `amend` | head | Change one lane of a running manifest, re-check, bump the epoch, rewrite `brief.md`. | `lanes.py amend lanes.json --lane a --add-files src/x.ts [--set-files L] [--remove-files L] [--depends-on L] [--provides L] [--consumes L] [--stubbed-on L] [--merge-after L]` | manifest, epoch, `brief.md` |
| `branch-check` | head | Branch-name collision check for `dts2/<stamp>/lane-<id>` (needs git 2.38+). | `lanes.py branch-check <stamp> --lanes a,b` | none |
| `son-command` | head | Print the son command line (uses the `son_model` setting); `--wrap` adds session id, stream-json and `son.json`. | `lanes.py son-command lanes.json --lane a --worktree ../wt-a [--wrap]` | none (prints argv) |
| `plan` | head | Admit lanes from a check-in list and a draft: spend estimates, feasibility, graph block, `--full` selection. Refused in a son. | `lanes.py plan --from-checkin checkin.json --draft draft.json [--outside "<item>: <why>"] [--full] [--max N] [--stamp S] [--autopilot] [--fullauto]` | run record, `scope.json`, `pending-items.json` |
| `status` | head | Lane status, heartbeat age, stall marks, routing records. | `lanes.py status <stamp>` | none (read-only) |
| `sendback` | head | Send a lane back for rework; counted atomically, at most two per lane. | `lanes.py sendback <stamp> --lane a --reason "<why>"` | `send-back-<n>.md`, status |
| `release` | head | Release a lane lease; a stale `--epoch` is refused. | `lanes.py release <stamp> --lane a [--epoch N]` | lease file |
| `fold` | head | Group blocked lanes into the fewest PRs; `--apply` records the originals as superseded by `--pr` (refused in a son). | `lanes.py fold <stamp> [--apply GROUP --pr N]` | run folder, merge journal (with `--apply`) |
| `preflight` | head | Pin the `claude` CLI version, test a real son launch (auth, plugin errors, head push dry-run, version skew), run `gc`. | `lanes.py preflight <stamp>` | run folder (pinned version) |
| `budget` | head | Budget report: caps, spend, reserved, loops, elapsed. | `lanes.py budget <stamp>` | none (read-only) |
| `loop` | head | Fullauto loop counter against `max_fullauto_loops`. | `lanes.py loop <stamp>` | budget counter |
| `spawn` | head | Start a son under every cap (turns, spend, model-call limit, sandbox). `--resume` continues the saved session. | `lanes.py spawn lanes.json --lane a --worktree ../wt-a [--resume] [--unsafe-no-sandbox]` | `son.json`, `exit.json`, status, budget and model ledgers |
| `call` | head | Run any other model call behind the shared limit, with a scrubbed environment. The command follows `--`. | `lanes.py call <stamp> --label vote-1 [--timeout S] [--cost-source claude\|none] [--prompt-file f] [--out f] -- <command ...>` | model-call ledger, `--out` file |
| `publish` | head | Push a finished lane branch and open or adopt its PR; a diff touching protected files parks the lane. Refused for a son, voter or council seat. | `lanes.py publish <stamp> --lane a [--branch B] [--base B] [--title T] [--body T]` | git push, one PR |
| `heartbeat` | either | Record a lane heartbeat or, with `--status`, its phase (goes through `transition`); a stale `--epoch` is ignored. | `lanes.py heartbeat <stamp> --lane a [--turn N] [--status pr-open\|done\|blocked\|incomplete] [--reason R] [--blocked-by ids] [--epoch N]` | status, lease renewal |
| `merge-order` | head | Print the merge order and who is next (honours `merge_after` and provider-first order). | `lanes.py merge-order lanes.json` | `merge-order.json` |
| `wait` | head | Block until a lane's phase or `exit.json` changes, or the timeout (seconds, hard deadline). | `lanes.py wait <stamp> [--timeout 600]` | none |
| `gc` | head | Close expired leases of lanes nobody is running. | `lanes.py gc` | lease files |
| `merge-plan` | head | Merge queue or serial rebase-test-merge plan; `git merge-tree --write-tree` probe of every lane. Merges nothing. | `lanes.py merge-plan lanes.json [--base origin/dev]` | `merge-order.json`, routing record |
| `merge-go` | head | Write `merge-go.md` for a verified head and base commit; refused in a son, on a red base, while the merge mutex is held, or when the lane changed files it does not own. | `lanes.py merge-go lanes.json --lane a --head <sha> [--base <sha>]` | `merge-go.md`, `merge-go.json`, merge journal |
| `audit` | head | List files a lane branch changed outside its owned set (the check `merge-go` runs). | `lanes.py audit lanes.json a --head <sha> [--base <sha>]` | none (read-only) |
| `merge-target` | head | Record the branch the run merges into (default `dev`); the default branch needs `--yes-default-branch`. Refused in a son. | `lanes.py merge-target <stamp> [--set dev] [--yes-default-branch]` | run folder |
| `merge-go-step` | head | Merge clearance for an autopilot step; same base-health and mutex refusal as `merge-go`. Refused in a son. | `lanes.py merge-go-step <stamp> --step 3 --head <sha> [--base <sha>]` | `merge-go.md`, merge journal |
| `gc-restore` | head | Restore `gc.auto` after an aborted run. Refused in a son. | `lanes.py gc-restore <stamp>` | git config `gc.auto` |
| `merge-done` | head | Mark a lane merged; when all are merged restore `gc.auto` and record the run end. | `lanes.py merge-done lanes.json --lane a` | merge order, run record |
| `transition` | either | The one writer of a lane's phase, against a table of legal moves. A son may report only pr-open, done, blocked, incomplete; starting and orphaned are the head's. | `lanes.py transition <stamp> --lane a --to pr-open [--reason R] [--blocked-by ids] [--turn N] [--epoch N]` | status |
| `shutdown` | head | Graceful end of a run: park running lanes, SIGTERM then SIGKILL the sons after the grace period, close leases, restore `gc.auto`. Refused in a son. | `lanes.py shutdown <stamp> [--grace-s 30]` | status, leases, run record |
| `reconcile` | head | Ask GitHub what exists for each lane (or, with `--step`, for a standalone autopilot step) before creating, merging or resuming. Refused in a son. | `lanes.py reconcile <stamp> [--step 3]` | status, merge order |
| `run-record` | head | Open (`--init`) or print the run's typed record `run.json`. | `lanes.py run-record <stamp> [--init] [--kind run\|autopilot]` | `run.json` (with `--init`) |
| `builder` | either | Append one builder row to `builders.jsonl`; the sha is confirmed against the branch tip and diff. | `lanes.py builder <stamp> --lane a --section 2 --branch dts2/<stamp>/lane-a-b1 --status done [--round N] [--sha S] [--pr N] [--base B]` | `builders.jsonl` |
| `run-resume` | head | What `run resume` reads: the run record and the newest row of each builder. | `lanes.py run-resume <stamp>` | none (read-only) |
| `fold-done` | head | Record that a fold group's PR is shipped. Refused in a son. | `lanes.py fold-done <stamp> --group <key> [--pr N]` | merge journal |
| `merge-resume` | head | Settle a merge a dead head left half done, by asking GitHub. Refused in a son. | `lanes.py merge-resume lanes.json` | merge journal, merge order |
| `walkthrough-failed` | head | Record a failed post-merge walkthrough and file one revert action item. Refused in a son. | `lanes.py walkthrough-failed <stamp> --lane a --reason "<why>"` | merge journal, action item |
| `fix-attempt` | head | Count a post-merge fix; past `post_merge_fix_attempts` open one revert PR (or park with the revert action item). Refused in a son. | `lanes.py fix-attempt <stamp> --lane a --reason "<why>"` | merge journal, revert branch and PR |
| `base-health` | head | Is the fetched `origin/<base>` green? `merge-go` refuses while it is red or the base moved. Refused in a son. | `lanes.py base-health <stamp>` | `base-health.json` |
| `merge-mutex` | head | The repo-wide merge mutex, held from the rebase to the post-merge PASS. Refused in a son. | `lanes.py merge-mutex <stamp> --lane a --op acquire\|release\|status` | mutex record, merge journal |
| `fold-close` | head | Close each superseded original PR with a link to the new one; journals each close. Refused in a son. | `lanes.py fold-close <stamp>` | closes PRs on GitHub, merge journal |
| `report` | head | The run as a markdown table plus run-wide sections (refusals, overrides, merge order, spend, per-son CI result, out-of-lane requests). | `lanes.py report <stamp> [--repo-url https://github.com/<owner>/<repo>]` | none (prints markdown) |
| `stop-check` | head | Whether fullauto may stop: nothing outstanding, ignoring items tied to a ledgered blocked PR; `--base` reads the end state from `origin/<base>`. | `lanes.py stop-check <stamp> --from-checkin checkin.json [--base dev]` | none |
| `approve-lane` | head | Record the user's yes for one lane (`dpp_full_ask_each_lane`). Refused in a son. | `lanes.py approve-lane <stamp> --lane a` | approval record |
| `override` | owner | The owner's override of a lane rule, logged to `state.md`; needs the human approval channel; refused in a son, a vote or the council. | `lanes.py override a --reason "<why>"` | `state.md` line |
| `mailbox` | either | The head/son mailbox. Son ops: ask, need-human, check, wait, park, merge-go-check, rules, request. Head ops: answer, decide (refused in a son). A wait that runs out parks the lane (`mailbox_wait_min`). | `lanes.py mailbox ask <stamp> --lane a --text "<question>"  \|  mailbox answer <stamp> --lane a --id q1 --text "<answer>"  \|  mailbox park <stamp> --lane a --reason context-guard [--session-id S]  \|  mailbox rules <stamp> --lane a --point start\|vote\|ship\|merge  \|  mailbox request <stamp> --lane a --files f1,f2 --text "<why>"  \|  mailbox decide <stamp> --lane a --id r1 --outcome escalate\|granted\|denied  \|  mailbox merge-go-check <stamp> --lane a [--worktree D]` | `questions/`, `merge-go.json`, status |
| `report-check` | head | Check the final report against lane ids; with `--stamp` also cross-check the son run records. | `lanes.py report-check dpp-report.md --lanes a,b [--stamp <stamp>]` | none (read-only) |

## 3. Standalone scripts (64 with a command line)

Invocation shown without the prefix `python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/`; add it and the closing `"`. Scripts marked `hook` read the hook JSON on stdin and are called by `hooks/*.sh`.

| Command | Role | What it does | Exact invocation | Writes / side effects |
|---|---|---|---|---|
| `action-items.py` | either (`reserve`, `release`, `fold`: head) | List and update the action-item file. | `action-items.py <repo> list \| done <row> \| add <group> <text...> [--id I --holder H --task T] \| assign <row> <agent> \| reserve <group> <count> --holder H \| release --holder H \| fold <lane_file> --holder H` | action-items file |
| `agent-memory.py` | either | Give each detected agent a project memory file from one shared source. | `agent-memory.py --write <dir> [--agents a,b] [--project P]` | memory files |
| `app-type-detect.py` | either | Detect the app type and print the readiness table. | `app-type-detect.py <repo> [--type web-app\|api\|cli\|library\|static-site] [--table]` | none |
| `approvals.py` | either | Human-only approval channel (`dts2_approvals` in `.claude/settings.local.json`). | `approvals.py [--repo R] check <kind> <key> [--session S] \| path` | none |
| `ballot_dispatch.py` | head | Run one council seat through the shared call limit; writes the ballot and its `.dispatch.json`. | `ballot_dispatch.py dispatch --seat S --model M --prompt-file F --out-dir D [--provider P] [-- argv]` | ballot, `.dispatch.json` |
| `briefs.py` | head | Son and lead briefs and the cached prompt prefix; starts no process. | `briefs.py son-brief <manifest> --lane L --epoch N [--max-bundle N --out F] \| prefix --stamp S \| dry-run <manifest> --lane L --worktree D \| lead-brief --stamp S [--task-file F --roster-json J --probe-json J]` | `brief.md` / `--out` file |
| `builder-audit.py` | head | Audit one builder's result against its owned files; exit 1 on a violation. | `builder-audit.py --base <ref> --owned <files> [--repo R --claimed-sha S --status S --attempt N]` | none (read-only) |
| `bump-version.py` | maintainer | Bump or verify the version in the four places it is recorded. | `bump-version.py <version> [--root R] [--check]` | version files (not with `--check`) |
| `changelog-join.py` | maintainer | Join `changelog.d/` fragments into the README `## Unreleased` section; dry run unless `--apply`. | `changelog-join.py [--root R] [--version V] [--apply] [--date D]` | README, deletes joined fragments (with `--apply`) |
| `check-in.py` | either | Complete/outstanding checklist against the end state. | `check-in.py (--items <ids> \| --from <file>) [--json]` | none (read-only) |
| `checks.py` | either | Deterministic checks (tests, types, lint, secret scan, scope) before any model vote, and the run ledger. | `checks.py run --stamp S [--cwd D --base B] \| gate --stamp S [--head H] \| summary --stamp S \| env-missing --stamp S <names...> \| scout-check --stamp S <file>` | `ledger.jsonl` |
| `intake.py` | either | Prompt intake queue: records prompts typed while the harness works, scores and classifies them (fold, clarify, steer) and renders the queue. | `intake.py add [--text T] [--source hook\|cli] \| list [--status S] [--json] \| resolve <id> --as fold\|clarify\|steer\|done [--note N] \| answer <id> --text T \| status \| hook`; `--root DIR`, `--threshold N` (60), `--budget N` (2) | `.harness/intake.jsonl`, `.harness/intake.md` |
| `clarity-score.py` | either | Requirement clarity score; the weakest component bounds it. | `clarity-score.py <ratings>` | none |
| `companion-gate.py` | either | Run-count gates for two costly companion skills. | `companion-gate.py check\|record --repo R --skill NAME [--base B]` | gate record |
| `context-guard.py` | hook | PostToolUse context guard (hook JSON on stdin). | `context-guard.py --tool-calls N --mb M [--stop]` | none |
| `context-tax.py` | maintainer | Measure always-loaded skill and agent metadata; exit 1 over budget. | `context-tax.py [--root R] [--budget N] [--max-description N]` | none |
| `fleet.py` | either | Machine-wide session registry and broadcast inbox. `list`, `show`, `logs`, `status`, `checkins` are read-only; `broadcast`, `label`, `checkin`, `prune` write to the fleet home. | `fleet.py list [--all --json] \| show <ref> [--json] \| logs <ref> [-n N] \| broadcast --kind note\|handoff\|pause\|knowledge\|checkin --text T [--to all\|harness\|repo:X\|id:X\|label:X] [--expires 24h] [--from-knowledge KEY] \| status [<id>] \| label <ref> <name> \| prune [--days 14] \| checkins [--since 24h] \| checkin --session ID --status TEXT [--blocker X] [--next N] [--question Q]` | `~/.dts2/fleet/` (`DTS2_FLEET_HOME`) |
| `ask_expert.py` | head | Repo decision support for `ask-expert` and `repo-sweep`: goal clarity score, memo checker, sweep ledger, and the guarded archive, backup and delete. Every subcommand prints JSON. | `ask_expert.py clarity --answers F [--asked N --threshold T] \| goal record --repo R --answers F \| check-report <file> \| scorecard --report F [--goal G] \| sweep add --ledger F --repo R --verdict V --confidence C --reason T --score N --salvage T [--report P] \| sweep show --ledger F \| archive --repo OWNER/NAME \| backup --repo OWNER/NAME [--dest D] \| delete --repo OWNER/NAME --confirm NAME --bundle P` (`delete` takes one repo and refuses without the exact name and a verified bundle) | `.harness/ask-expert/`, `~/.dts2/repo-backups/` |
| `council.py` | head | Autopilot council (with `--allow-research`, ask-expert runs may also decide `RESEARCH` with a `## Research brief`): eligibility, dossier, tally, decision check, routing, blinding, fencing, ledger, seats, swap, next round. | `council.py eligible --votes-dir D \| dossier --votes-dir D --out F \| tally <ballots...> \| check-decision <decision> --tally T --entries E [--ledger L --head H] \| route --ledger L [--head H --votes V --decision APPROVE\|FIX\|STRIKE] [--allow-research] \| blind --proposals P --out O --voters V --seed S \| wrap <file\|-> [--source S --max-chars N] \| ledger --ballots-dir D --tally T --decision X --step N --stamp S --out F \| seats --usable U [--config C --failed F] \| swap \| identical \| next-round --votes-dir D --step N --kind plan\|build [--retry N --revote]` | council record, vote folders |
| `delegate.py` | either | Resolve model, tier and effort for a dispatch seat. | `delegate.py --agent A --seat S --complexity C [--profile-dir D --budget B --lead-provider P --effort E]` | none |
| `deploy-detect.py` | either | Detect how a repo deploys, by file presence only. | `deploy-detect.py <repo>` | none |
| `doctor.py` | either | Preflight checks for this machine: python, git, claude, sandbox, bwrap, socat, auth method, platform. | `doctor.py [--json]` | none |
| `ensure-ignored.py` | either | Append missing harness entries to `.gitignore`. | `ensure-ignored.py <repo> [--extra paths...]` | `.gitignore` |
| `env-detect.py` | either | Report OS, WSL status, live Claude home and which agent CLIs are on PATH. No flags. | `env-detect.py` | none |
| `failover.py` | either | Pick the next lead provider on a usage or token limit. | `failover.py --current P [--profile-dir D --exclude P2]` | none |
| `findings.py` | either | Merge reviewer findings (calibrate severity, dedupe) and render the final-review digest. | `findings.py merge <reports...> [--json] \| digest <reports...> [--repo R --base B]` | none |
| `flags_collect.py` | head | Collect a builder report's `FLAGS:` block into `flags.md`. | `flags_collect.py --stamp S --builder B [--repo R --report-file F]` | `flags.md` |
| `guard.py` | hook | PreToolUse son deny list and merge gate (hook JSON on stdin). | `guard.py --mode son\|merge [--cwd D]` | `merge-guard.log` (denials) |
| `handoff-write.py` | either | Render `handoff/latest.md` (state, action items, deploy block, latest receipt, Rollback line). | `handoff-write.py <repo>` | handoff file |
| `harness-lock.py` | head (only a head may lock) | Lock a shared harness record for one writer. | `harness-lock.py acquire\|release\|check --file F --holder H [--role head\|son --ttl-sec N --lock-dir D]` | lock file |
| `head_publish.py` | head | The head pushes and opens one PR per lane, merges when preconditions hold, and bootstraps each lane. Refused when `DTS2_SON` is set. | `head_publish.py [--repo R] publish --lane L --branch B --base B --title T [--body X] \| merge <pr> [--verifier-ok --default-branch B --deploys-production] \| bootstrap --stamp S --lane L --worktree D` | git push, PRs, `son.env` |
| `lessons.py` | either | Maintain the lessons file: promotions, regressions, 90-day pruning. | `lessons.py <repo> promote <lesson> [--lives-at P --today D] \| regress <lesson> [--today D] \| stats \| prune [--today D --stale-days N]` | lessons file |
| `machine-prep.py` | user (via skill) | Audit a machine against a blueprint profile; `apply` disables plugins (reversible). | `machine-prep.py audit\|plan\|apply [--profile P --home H --claude-home C --tier light\|standard\|strict --days N --project P]` | settings backup, plugin settings (`apply`) |
| `marketing-select.py` | either | Ordered marketing-skills subset for the go-to-market pass. | `marketing-select.py [--facts F]` | none |
| `metrics.py` | either | Append run metrics (one row per stamp) and print a trend line. | `metrics.py <repo> append --stamp S --rounds N --duration D --verdict V [--agents A --failures F] \| trend [--last N]` | metrics file |
| `plan-gate.py` | either | PASS or FAIL for a lead plan before the checkpoint. | `plan-gate.py <plan> [--json]` | none |
| `plan_graph.py` | head | Plan graph for a lane manifest: contracts, owners, cycles, critical path, six-section lane brief. | `plan_graph.py [--cwd D] analyse <manifest> \| merge-order <manifest> --runs-dir D \| brief <manifest> --lane L` | `merge-order.json` (`merge-order`) |
| `plugin_options.py` | either | Per-user knobs from `CLAUDE_PLUGIN_OPTION_<KEY>` and the plugin data directory. | `plugin_options.py show \| get KEY [--default V] \| data-dir` | none |
| `policy_gate.py` | hook | Declarative policy gate (`templates/policy.json`); hook JSON on stdin. | `policy_gate.py [--cwd D]` | `policy-gate.log` (denials) |
| `pr_payload.py` | hook | Payload helpers for the PR-receipt hook; `decisions` prints the PR decisions section. | `pr_payload.py parse \| view --body-out F \| body --body-file F --receipt-file R \| decisions --ledger L \| payload [pairs...]` | none |
| `prod-scaffold.py` | either | Write the CI workflow and production scaffolding; never overwrites. | `prod-scaffold.py <repo> --app-type web-app\|api\|cli\|library\|static-site\|unknown [--no-ci]` | CI workflow, runbook, `ops/` notes |
| `protected.py` | head | Protected paths a son's diff must not touch. | `protected.py <repo> paths \| check [names...]` | none |
| `provider_report.py` | either | Provider-neutral brief footer and validator for the fenced JSON report. | `provider_report.py footer \| check <file\|->` | none |
| `receipts_sign.py` | head | Hash-chained journal and HMAC-signed receipts. | `receipts_sign.py append JOURNAL BODY_JSON \| verify JOURNAL \| sign FILE \| check FILE SIG` | journal, signature |
| `repo-size.py` | either | Size repos and recommend a team tier. | `repo-size.py [repos ...] [--max-builders N] [--json]` | none |
| `review_split.py` | head | Above a line threshold, split a diff into path-group slices, one reviewer each. | `review_split.py plan --base B [--repo R --threshold N --max-reviewers N]` | none |
| `rollback_ref.py` | head | Pin `refs/dts2/<stamp>/base` and print the human-run Rollback line. Rolls nothing back. | `rollback_ref.py create\|line --stamp S [--repo R] [--sha S]` | git ref (`create`) |
| `roster.py` | either | Detect installed coding agents and resolve the roster into seats. | `roster.py detect [--project P] \| resolve [--config C] \| probe [--config C] \| model --agent A --tier T \| command --agent A --role R [--tier --effort --prompt-file --workspace --model] \| classify --agent A --role R --exit-code N [--axis --usable]` | none |
| `run_metrics.py` | either | Run metrics with lanes, tokens, wall-clock. | `run_metrics.py plan-check <manifest> \| record <repo> --stamp S --rounds N --duration D --verdict V --lanes N --tokens N --wall-clock-s N [--agents --failures --size-class]` | metrics file |
| `run_report.py` | either | Markdown table of one run; same view as `lanes.py report`. | `run_report.py <stamp> [--runs-dir D] [--repo-url U]` | none |
| `scope-check.py` | either | Detect workspace root, member, single repo or none; `--lessons` adds matching lessons. | `scope-check.py [path] [--lessons] [--files F]` | none |
| `seat_swap.py` | head | Council seat substitution and identical-findings ledger note. | `seat_swap.py swap --seats S --failed F [--ledger L --step N --reason R] \| identical --votes-dir D --ledger L --step N --prev P --curr C` | ledger note |
| `session_end.py` | hook | Release the lane leases this session took (hook JSON on stdin). | `session_end.py` | lease files |
| `settings_cache.py` | either | Parsed settings from `.harness/config.yaml` and the local frontmatter, cached. | `settings_cache.py [repo] [--get key]` | cache file |
| `hooks-setup.py` | either | List, recommend and add optional hooks (`command-guard`, `auto-format`, `test-on-stop`, `notify`, `merge-on-green`, `db-guard`, `migration-check`) to settings; merge only, backup first. | `hooks-setup.py list \| recommend [--cwd D --home H] \| apply --ids A,B [--scope project\|local\|user --cwd D --home H --dry-run]` | settings file, `.claude/hooks/dts2/` (`apply`) |
| `improve-scan.py` | either | Read-only audit of hooks, MCP servers, database tooling, plugins, commands, subagents, permissions, CI and agent docs; ranked recommendations. | `improve-scan.py [--cwd D] [--home H]` | none |
| `skill-suggest.py` | either | Ranked candidate skill names from repo facts. | `skill-suggest.py [--facts F]` | none |
| `skills-check.py` | either | Pre-run check of harness version, marketplaces, companion and keep-list skills; proposal-only updates. | `skills-check.py <repo> [--fix] [--swap OLD=REF] [--apply-update NAME=SHA] [--no-upstream] [--force-full] [--son-root P] [--home H] [--plugin-root P]` | `skill-updates.json`, installed skills (`--fix`) |
| `spawn_dry_run.py` | hook | Print the composed brief and command without starting anything (hook JSON on stdin). | `spawn_dry_run.py [--agent-dry-run]` | none |
| `state_io.py` | maintainer | Upgrade every record under the runs folder to the current version; safe to repeat. | `state_io.py migrate-all [repo]` | run records |
| `subagent_report.py` | hook | Report-section check for builder, reviewer, verifier (hook JSON on stdin). | `subagent_report.py --event stop\|handback` | none |
| `task-ledger.py` | head | Open PRs, bundled tasks and the user-input items that block them. | `task-ledger.py <stamp> [--cwd D --runs-dir D --out F --resolved]` | `task-ledger.md` |
| `upgrade-check.py` | either | Compare the pre-upgrade version with the installed one. | `upgrade-check.py --from-file F [--plugin-json J]` | none |
| `usage-scan.py` | either | Count Skill, Agent and MCP tool uses in recent transcripts; read-only. | `usage-scan.py --claude-home C [--days N]` | none |
| `walkthrough_fallback.py` | head | Playwright fallback for the post-merge walkthrough: sandbox, host allowlist, no `file://`. | `walkthrough_fallback.py --out F --url U [--url U2] [--cwd D]` | walkthrough output |
| `agent_events.py` | hook | Hook handlers: verifier stop gate, StopFailure and PermissionDenied action items. | `agent_events.py subagent-stop\|stop-failure\|permission-denied` | action items |

Also outside `scripts/`: `sdk/dts2-run.py <task> [--repo R] [--yes] [--api-key-env V] [--second-opinion none|codex|gemini] [--ship] [--live-only]` (headless pipeline, run by the `sdk` skill) and `evals/run.py [--fixture F] [--baseline B] [--results-dir D] [--update-baseline] [--runs N] [--arm-b-env VAR=VAL]` (smoke evals; by hand). The root `Makefile` has `make test`, `make doctor`, `make check-version` and `make package`.

Library modules, not invoked directly (15): `_load.py`, `contracts.py`, `eval_stats.py`, `harness_skew.py`, `mdparse.py`, `miniyaml.py`, `model_call.py`, `ownership_audit.py`, `prep-tiers.py`, `proc.py`, `profiles.py`, `skill_pins.py`, `son_launch.py`, `son_stream.py`, `state_ids.py`. The modules of `scripts/lanes/` are libraries behind `lanes.py` and have no command line either.

## 4. Skills (23 slash commands)

Typed as `/dts2:<name>`. `user only` means `disable-model-invocation: true`: the model never starts it, a person must type it.

| Command | Role | What it does | Exact invocation | Writes / side effects |
|---|---|---|---|---|
| `/dts2:onboard` | user only | Explain the harness and recommend where to start; an optional last step adds hooks you pick. | `/dts2:onboard` | settings and `.claude/hooks/dts2/` (only on a pick) |
| `/dts2:machine-prep` | user only | Audit this computer's agent tooling and prune to the blueprint (once per machine). | `/dts2:machine-prep` | plugin settings (with backup) |
| `/dts2:setup` | user or model | Interview to an approved end state, then scaffold harness config in one repo, many repos or a workspace. | `/dts2:setup [path ...] [--scaffold-only]` | end-state file, config, CI, gitignore |
| `/dts2:run` | user or model | Plan, build, review and verify one task with a human at the two checkpoints; ends with a receipt. | `/dts2:run <task> \| resume \| section <#> \| add secret NAME \| review-pr <number>` | branches, receipt, state, PR |
| `/dts2:learn` | user or model | Consolidate review findings into lessons; prune stale ones only after the user approves. | `/dts2:learn [promote L-NNN]` | lessons file |
| `/dts2:sdk` | user only | Set up and run the pipeline headless with the Agent SDK (CI, cron, servers, WSL). | `/dts2:sdk` | SDK runner config |
| `/dts2:evolve` | user or model | Change the harness itself in its source repo: edit, validate, test, bump, commit; push only on an explicit yes. | `/dts2:evolve [deploy]` | plugin source files, version, commit |
| `/dts2:action-items` | user or model | Show open Secrets, Decisions, Handoff, Deploy and Promotions items; mark done, add, assign. | `/dts2:action-items [done <id> \| add <group> <text> \| assign <id> <agent>]` | action-items file |
| `/dts2:gtm` | user or model | Go-to-market pass: installs marketing-skills if missing, ends with a readiness scorecard. | `/dts2:gtm` | readiness file, gitignore |
| `/dts2:ship` | user or model | Ship the current branch as a PR: checks, secret scan, verifier and reviewer, receipt, push, open PR; then sweep stale branches. Never merges. | `/dts2:ship [base]` | receipt, push, PR, branch clean-up (after a yes) |
| `/dts2:feature` | user or model | Add a feature to the roadmap: clarity score, interview, end state updated, plan PR. Plans only. | `/dts2:feature <description>` | end-state file, plan PR |
| `/dts2:autopilot` | user or model (a son runs it with `--son`) | Run harness steps unattended; a three-provider gate and a council replace the checkpoints. One branch and PR per step. | `/dts2:autopilot <steps> \| resume \| status \| --son <stamp>/<lane>` | branches, PRs, receipts, council record |
| `/dts2:dpp` | head | Run several autopilot lanes in parallel as headless sons under a head that plans, supervises and serialises merges. | `/dts2:dpp [dry-run] [--full] [resume]` | run folder, lane worktrees, PRs, report |
| `/dts2:dpp-full` | user only | `dpp --full`: also fills lanes from a delegation scan and keeps dispatching. | `/dts2:dpp-full` | as `dpp` |
| `/dts2:fullauto` | user only | `dpp-full` with autopilot forced on, looping check-in until nothing is outstanding. | `/dts2:fullauto` | as `dpp` |
| `/dts2:check-in` | user or model | Read-only progress against the approved end state: `N of M complete`. `all` reports check-in items from every session on the machine and, after a yes, asks them for fresh ones. | `/dts2:check-in [all [--since 24h]]` | none (broadcast inbox on a yes) |
| `/dts2:model` | user only | Choose which agent provider fills the lead, advisory and sign-off seats; records `lead_provider`. | `/dts2:model` | settings file |
| `/dts2:cooldown` | user only | Pause an agent that hit a usage limit until its reset date, resume it, or list what is paused. | `/dts2:cooldown set <agent> <date or duration> [reason] \| clear <agent> \| list` | agent status file |
| `/dts2:fleet` | user or model | See every harness session on this computer; read status, logs and ledgers without interrupting them; broadcast a note, handoff, pause or knowledge finding to all (confirms first). | `/dts2:fleet list \| show <ref> \| logs <ref> [-n N] \| broadcast --kind K --text T [--to ...] \| status [<id>] \| label <ref> <name> \| prune` | fleet home (`~/.dts2/fleet`) |
| `/dts2:knowledge` | user only | Keep your own standing preferences, glossary terms and cross-project learnings in a private store that syncs across devices (private GitHub repo, Cloudflare Worker + D1, or a drive-synced folder). | `setup \| join \| set <key> <value> \| get <key> \| find <text> \| list \| rm <key> \| sync \| status` | personal knowledge store |
| `/dts2:find-skills` | user or model | Rescan the repo, audit every improvement option (skills, hooks, MCP servers, plugins, commands, subagents, permissions, CI), ask, and wire in the picks on a yes. | `/dts2:find-skills` | keep list, settings (on a yes) |
| `/dts2:steer` | user or model | Stop running work and redirect it. Finishes the current atomic step, dispatches nothing new, checkpoints a handoff, reviews open intake items, re-plans to the new direction, confirms in one short message and resumes. | `/dts2:steer <new direction>` | handoff file, intake queue, plan |
| `/dts2:ask-expert` | user or model | Decide the fate of one repo: asks your goal in plain words, reads the code, compares it with what you said and with your active repos, runs a three-provider expert panel (council and research if it stalls) and writes a one-page memo: keep, fold, template, archive or delete. Changes nothing. | `/dts2:ask-expert [repo] ["what I'm unsure about"]` | `.harness/ask-expert/<repo>/` |
| `/dts2:repo-sweep` | user or model | Quick ask-expert pass over every repo of an owner, oldest first, then one cleanup screen. Keep, fold and template write a to-do file; archive uses `gh repo archive`; delete is per repo after a backup bundle and a typed name. | `/dts2:repo-sweep [owner]` | `.harness/ask-expert/`, archived repos, `~/.dts2/repo-backups/` |

## 5. Agents (7)

Dispatched by the skills with the Agent tool; nobody types them.

| Agent | Read-only or writer | What it does | When the head spawns it | Exact invocation |
|---|---|---|---|---|
| `dts2:lead` | read-only | Slices the end state into a DAG of tasks with exclusive file ownership and picks reviewer axes. Never writes code. | At the start of `run` and `autopilot`, after the scout, to produce the plan. | `Agent(subagent_type: dts2:lead)` |
| `dts2:builder` | writer | Implements exactly one builder section inside its owned file set; does not review its own work. | After the plan is approved, one per section, in parallel on disjoint files. | `Agent(subagent_type: dts2:builder)` |
| `dts2:fixer` | writer | Fresh-context fix for round 2 on the same failure: applies the one hypothesis the lead picked. | When a fix round 1 failed on the same finding. | `Agent(subagent_type: dts2:fixer)` |
| `dts2:reviewer` | read-only | Reviews a diff on one or all axes and returns severity-rated findings and a verdict. | After builders finish; one per axis or per diff slice. | `Agent(subagent_type: dts2:reviewer)` |
| `dts2:verifier` | read-only (Bash for checks; cannot write files) | Runs configured build, type, lint and test commands, checks for stubs, walks screens when asked. Evidence only. | After review, before the Ship checkpoint. | `Agent(subagent_type: dts2:verifier)` |
| `dts2:scout` | read-only (Bash for configured commands) | Measures a repo, detects other harnesses and a marketing surface, recommends team tier, builder count and reviewer axes. | First, before planning. | `Agent(subagent_type: dts2:scout)` |
| `dts2:auditor` | read-only (Bash) | Inventories installed agent tooling against a blueprint profile and proposes keep, disable and setup. Never changes anything. | From `machine-prep`. | `Agent(subagent_type: dts2:auditor)` |

## 6. Hooks (16 rows, 25 registrations in `hooks/hooks.json`)

Registered in `hooks/hooks.json` and run by Claude Code. Agents do not call hooks; they only meet their effect (a denial, a blocked stop, a context note). Every hook honours the `enabled` setting in `.claude/dts2-harness.local.md`.

| Event (matcher) | Script | Blocks or allows |
|---|---|---|
| SessionStart | `hooks/session-lessons.sh` | Allows. Puts recent lessons, open state and action items into context (inside the untrusted-content fence, capped at 4000 characters). |
| SessionStart | `hooks/session-cooldowns.sh` | Allows. Prints which agents are cooling down after a usage limit and which just came back (`cooldowns.py session-note`); silent when none. |
| SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd | `hooks/fleet-session.sh` | Allows, except one keep-going at Stop for an undelivered `handoff` or `pause` broadcast. Registers the session, tracks state and heartbeat, and delivers fleet broadcasts once per session. |
| Stop | `hooks/stop-checks.sh` | Allows by default; with `stop_checks_block: true` a red check blocks the stop once. Quick typecheck and lint on changed files; skipped in a son. |
| PostToolUse (`Bash`: `gh pr create`, `gh pr edit`, `gh api`) | `hooks/pr-receipt.sh` | Never blocks. Makes sure a PR body has a `## Change receipt`; does nothing in a son. |
| PostToolUse (`Bash\|Edit\|Write\|Agent`) and PostToolBatch | `hooks/context-guard.sh` | Advises, or with `context_guard_stop: true` ends the turn, on a context spike before the plan checkpoint; parks a son. |
| PostToolUse (`SubagentHandback`) and SubagentStop (builder, reviewer, verifier) | `hooks/subagent-report.sh` | Blocks once per agent when a report lacks the sections its contract names. |
| PreToolUse (`Bash`) | `hooks/merge-guard.sh` | Denies force-push and any merge or protected-branch push unless a lane's `merge-go.md` names the head and base commit. |
| PreToolUse (`Bash`) | `hooks/policy-gate.sh` | Denies force-push, `--admin`, deploy CLIs, `gh secret`, `vercel env`, a bare `env`, `gh repo delete`; merges and default-branch pushes need the person's approval. |
| PreToolUse (`Bash`, `lanes.py spawn ... --dry-run`; and `Agent`) | `hooks/spawn-dry-run.sh` | Denies the call and prints the brief and command so nothing starts (Agent: only with `spawn_dry_run: true`). |
| PreCompact | `hooks/pre-compact.sh` | Allows. Refreshes the handoff file. |
| SubagentStop (verifier) | `hooks/subagent-stop.sh` | Blocks once when the run ledger lacks one of the five check lines. |
| StopFailure | `hooks/stop-failure.sh` | Allows. Files a Handoff action item naming the API error. |
| PermissionDenied | `hooks/permission-denied.sh` | Allows. Files a Handoff action item naming the denied tool. |
| SessionEnd | `hooks/session-end.sh` | Allows. Releases only the lane leases this session took, then refreshes the handoff. |
| UserPromptSubmit | `hooks/prompt-intake.sh` | Never blocks. Appends each prompt typed while the harness works to the intake queue, classifies it and injects a one-line instruction for the agent. Off with `intake: false` in `.claude/dts2-harness.local.md`. |

`hooks/lib-settings.sh` is a shared helper, not a registered hook.

### `/dts2:fleet` in short

One command for every harness session on the computer. Hooks register each session under `~/.dts2/fleet/sessions/`; the views read that registry and the sessions' own files and never touch a running session.

- `/dts2:fleet list` shows label or short id, repo@branch, state, last seen, turns and pending broadcasts. `show <ref>` adds the handoff, task ledger tail, open intake items, lanes and cooldowns; `logs <ref> -n 20` shows the last turns.
- `/dts2:fleet broadcast --kind handoff --text "Plugin update coming. Finish your step, write the handoff, stop."` reaches each target session once: on its next prompt, after its next tool call, or when it is about to go idle. Kinds are `note`, `handoff`, `pause`, `knowledge` and `checkin`. The skill shows how many live sessions match and asks before sending.
- `/dts2:fleet status` shows which sessions picked a broadcast up. A session idle at the prompt picks it up only when next touched.

## 7. Common flows

Copy-paste sequences from `GUIDE.md` section 3. Define the shorthand once per shell: `lanes() { python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/lanes.py" "$@"; }`. Placeholders: `<stamp>` run stamp, `a` lane id, `<sha>` a commit.

1. Start a lane run (head).

```
lanes plan --from-checkin checkin.json --draft draft.json
lanes check lanes.json
lanes approve-lane <stamp> --lane a          # only when dpp_full_ask_each_lane is true
lanes preflight <stamp>
lanes lease lanes.json --lane a --epoch 1
git worktree add ../wt-a -b dts2/<stamp>/lane-a
lanes spawn lanes.json --lane a --worktree ../wt-a
lanes wait <stamp> --timeout 600
lanes status <stamp>
```

2. Son hand-over (inside a son; the son commits, never pushes).

```
lanes heartbeat <stamp> --lane a
lanes builder <stamp> --lane a --section 1 --branch dts2/<stamp>/lane-a-b1 --status done --sha <sha>
lanes mailbox ask <stamp> --lane a --text "which table owns the order ids?"
lanes mailbox wait <stamp> --lane a --id q1
lanes transition <stamp> --lane a --to pr-open
```

3. Head merge-go (head only).

```
lanes merge-order lanes.json
lanes reconcile <stamp>
lanes base-health <stamp>
lanes merge-mutex <stamp> --lane a --op acquire
lanes audit lanes.json a --head <sha>
lanes merge-go lanes.json --lane a --head <sha>
gh pr merge <pr> --merge
lanes merge-mutex <stamp> --lane a --op release
lanes merge-done lanes.json --lane a
```

`gh pr merge` passes the merge guard only because `merge-go.md` now names the head and base commit; the policy gate also needs the person's approval for the merge. After a failed post-merge walkthrough run `lanes walkthrough-failed <stamp> --lane a --reason "<why>"` and `lanes fix-attempt <stamp> --lane a --reason "<why>"`.

4. Publish a finished lane (head only; refused in a son, a voter or a council seat).

```
lanes publish <stamp> --lane a --title "dts2: lane a"
lanes fold <stamp>
lanes fold <stamp> --apply <group> --pr <n>
lanes fold-close <stamp>
```

`fold` lists the groups; `fold --apply` records the originals as superseded by the new PR; `fold-close` closes them. `publish` pushes the branch and opens or adopts one PR; a diff that touches protected files parks the lane instead.

5. Council vote (head; only after three failed gate rounds).

```
python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/checks.py" run --stamp <stamp>
python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/council.py" eligible --votes-dir <votes>
python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/council.py" dossier --votes-dir <votes> --out <dossier.md>
python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/council.py" next-round --votes-dir <votes> --step 3 --kind build
python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/ballot_dispatch.py" dispatch --seat s1 --model <model> --prompt-file <prompt> --out-dir <votes>
python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/council.py" tally <ballot files>
python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/council.py" ledger --ballots-dir <votes> --tally <tally.json> --decision APPROVE --step 3 --stamp <stamp> --out <council.md>
```

6. Report ops (end of a run).

```
lanes report <stamp> --repo-url https://github.com/<owner>/<repo>
lanes report-check dpp-report.md --lanes a,b --stamp <stamp>
python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/task-ledger.py" <stamp>
lanes shutdown <stamp>
```

2. Adding instructions while a run is going.

```
/dts2:steer use the Postgres schema instead    # stop and redirect: finishes the current step first
python3 -I "$CLAUDE_PLUGIN_ROOT/scripts/intake.py" list    # the queue: fold, clarify and set items
```

Plain typing needs no command. A prompt is recorded as a fold (added to the ledger, the run goes on) or a clarify (may conflict; the agent asks at the next safe point before acting on it).

## 8. Changelogs

- Released versions: `../CHANGELOG.md`, newest first, [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format (Added, Changed, Fixed, Security). Its version headings are exactly `## [x.y.z]`.
- Not yet released: the `## Unreleased` section of `../README.md`. Each batch of work adds one fragment `../changelog.d/batch-<n>.md` (bullets only, each starting with its gap id such as `G-30`); the release step `scripts/changelog-join.py --apply` folds the fragments into the README and then into `CHANGELOG.md`. Read `../changelog.d/README.md` for the fragment rules.
- Per-command detail for a release: `INVENTORY.md` section 9 (3.11.0) and section 7 (3.10.0); the one-page digest of both: `GUIDE.md` section 5.

How to read a release section: open [3.11.0](../CHANGELOG.md#3110) and read the one-paragraph summary under the heading, then `### Added` (one bullet per gap id, each naming the script, command or setting it adds), then `### Fixed`. The 3.11.0 summary also records that the optional cross-model review step was skipped for that release by decision of the maintainer; CI reviews ran on every PR. [3.10.0](../CHANGELOG.md#3100) has Added, Changed, Fixed and Security; its Added list names the 35 lane commands that existed then. To find the release that introduced a command, search `INVENTORY.md` for the command: its "Since" column says `new` or `changed` for 3.10.0, and section 9 lists 3.11.0.

