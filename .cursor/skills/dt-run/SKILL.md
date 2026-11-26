---
name: dt-run
description: "Run the dts2 plan, build, review, verify pipeline on a task in one repo or workspace: sizes the team, plans against the end state, builds with parallel builders, reviews, ends with a receipt. Use to run the harness or for a multi-file, cross-repo change."
disable-model-invocation: true
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-run/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Run — plan, build, review, verify, ship

Follow the phases in order. Every agent dispatch uses the Agent tool with `subagent_type: dt:<role>` and a `model` override taken from `roster.py model` (claude: `economy` → `haiku`, `standard` → `sonnet`, `frontier` → `opus`). The lead and the verifier always run on `frontier`: frontier is for advice and sign-off only, never for a builder (Rule 9.2).

If the request is `run add secret NAME`, run the **Pre-check** below, then skip to **Add secret mode**.

## Phase files
Read the file for a phase only when you reach it; do not read ahead. All files are in this folder.

| File | Read when |
|---|---|
| `phase-0-size.md` | Read `phase-0-size.md` (same folder) when you reach Phase 0: size the team and the Budget check. |
| `phase-1-plan.md` | Read `phase-1-plan.md` (same folder) when you reach Phase 1: the lead plans and the Plan checkpoint. |
| `phase-2-build.md` | Read `phase-2-build.md` (same folder) when you reach Phase 2: parallel builders, Secrets, Continuous dispatch. |
| `phase-3-review.md` | Read `phase-3-review.md` (same folder) when you reach Phase 3: review, verify, the Finish pass and Code finish pass. |
| `phase-4-ship.md` | Read `phase-4-ship.md` (same folder) when you reach Phase 4: the Ship checkpoint, After ship, Deployment verification. |
| `modes.md` | Read `modes.md` (same folder) for `run add secret NAME`, `run review-pr`, or the Status lines. |
| `operations.md` | Read `operations.md` (same folder) for isolation and merging (Rule 10), a stalled lead (Rule 8.7), the Context guard, or a question from the user. |

## Companion skills
A companion skill is used by installing it if missing, with the `the publisher's installer for` command its entry in Companion skills in `.harness/discipline.md` gives, then running `/<name>`. The pre-check normally installs them all already.

## Preflight

### Pre-check (every run command)
Runs first, before anything else, on every entry: `run <task>`, `run resume`, `run review-pr`, `run add secret`, and the `ship`, `feature` and `autopilot` skills. Run `python3 "$PLUGIN/scripts/dt_gate.py" bridge skills-check.py <repo> --fix` and read its JSON. It changes no repo code and never pushes.

The pre-check has two speeds, and it picks for itself (`skills.freshness` says which ran). The **first run each day** is the **full** sweep: it refreshes the plugin marketplaces, reads the published harness version, writes update proposals (nothing is updated in bulk), and checks every skill for removal upstream — the network-heavy part, so it happens once a day and writes the date to `.harness/.skills-checked`. **Every other run that day** is the **fast** path: a filesystem-only check that a skill is still present and installs any that are missing, plus acting on an upgrade already detected. The fast path makes no network calls and returns in well under a second; `freshness: "fast"` means the daily sweep was skipped, not that anything is wrong. `--force-full` runs the sweep now regardless. So the cost the user feels (tens of seconds of `a package launcher`/`gh` calls) lands on the day's first command only, not on every run.
1. **Upgrade re-entry.** `harness.resume_upgrade` is set when `.harness/upgrade-from.txt` exists (a previous pre-check saved the spot and started an upgrade):
   - `advanced: true` → read `.harness/handoff/latest.md` (its `## State`, `## Open items`, `## Next action`), delete `.harness/upgrade-from.txt`, print `Upgraded <from> -> <to>; resuming: <next action>.`, run `skills-check.py <repo> --fix` once more (the new version's companion list), then continue the command the user just ran; when they ran a bare `run` or `run resume`, continue with the handoff's next action.
   - `same: true` → the new version has not loaded. Say `Still on <to>: run /reload-plugins (or restart Claude Code), then re-run the same command. If it stays on <to>, delete .harness/upgrade-from.txt to skip this upgrade.` and stop.
   - neither (`from` newer than `to`, a downgrade, or `from: null`) → delete the marker, print `Upgrade marker cleared (<from> -> <to>).` and continue.
2. **Newer harness.** `harness.upgrade_started: true` means a newer dts2-harness was published and is now installed: the script wrote the handoff (`.harness/handoff/latest.md`), refreshed the marketplaces with `claude plugin marketplace update`, ran `claude plugin update dt@dts2`, and only after that succeeded wrote the installed version to `.harness/upgrade-from.txt`. Say exactly `dts2-harness <installed> -> <published> is available and installed. Your spot is saved in .harness/handoff/latest.md. Run /reload-plugins (or restart Claude Code), then re-run the same command; the upgrade finishes itself.` and stop. Do not start the task on the old version. `upgrade_available: true` with `upgrade_failed` set → the update did not install (no `claude` CLI, or it failed): say `dts2-harness <published> is available but the update failed: <one line>. Run /plugin marketplace update dts2 and /plugin install dt@dts2 yourself (the agent cannot run `/plugin`), then reload.` and continue on the current version.
3. **Other plugins.** `plugins_updated` non-empty with no harness upgrade → one line `Updated plugins: <list>; they load after /reload-plugins.` and continue.
4. **Skills.** Every companion skill (see Companion skills in `.harness/discipline.md`) and every skill in `.harness/keep.yaml` (`/dt-find-skills`, onboarding and setup picks) is installed where Claude Code sees it (`.claude/skills/<name>`, installed with `-a claude-code --copy -y` because a bare install's symlink silently fails on Windows); a missing one is installed on any run, fast or full. On a **full** run (`freshness: "full"`), retired skills whose `skills-lock.json` source confirms them are also removed (`retired_kept` lists same-named skills from elsewhere, left alone), skills gone upstream are detected, and update proposals are written for every skill, pinned or not (nothing is updated in bulk); a **fast** run skips those three. Print one line: `Skills: <n> ready, <g> gone upstream, <f> failed, <r> rejected (<freshness>)`.
   - `gone`: a skill that no longer exists upstream. Show its ranked `candidates` (ref and install count; the gone skill's own repo is searched too, since renames live there) and ask once per skill: `<name> is gone upstream. Replace it with <top ref> (<installs> installs)? (yes / pick another / no)`. On yes run `skills-check.py <repo> --swap <name>=<ref>`, which installs it, rewrites keep.yaml and removes the old copy. Nothing third-party is installed without that yes. On no, or with no candidates, add a Decisions action item `find a replacement for <name>`. Under autopilot, never swap: add the Decisions item with the candidates.
   - `failed`: add a Decisions action item with its install command. `rejected`: a keep.yaml entry whose name or source is not an allowlisted ref (`owner/repo@skill` or `https://github.com/owner/repo --skill name`); say so and never run it.
   - `tracked_skipped`: skills the pre-check would not touch because the repo commits their files (git-tracked under `.claude/skills/` or `.agents/skills/`, or a tracked `skills-lock.json`). The pre-check never deletes or overwrites a tracked file, on a full run, a fast run or `--force-full`: tracked files are put back byte-for-byte after each `the publisher's skill installer` call and a tracked retired skill is not removed. Print one line `Kept tracked skills: <name> (<step>[, reverted <n> files])` listing each; a non-empty `reverted` means the CLI tried to change committed files, so add a Decisions action item `update tracked skill <name> by hand and commit it`. An `apply-update` entry with `tracked_check: "unavailable"` means git could not list tracked files, so the update was not applied: say `Skill update not applied: could not list tracked files (git).`
   - Report keys: `proposals`, `install_skipped`, `update_skipped` and `applied` (alongside `installed`, `missing`, `gone`, `failed`, `rejected` and `tracked_skipped`). `install_skipped` is kept for older reports and stays empty: a missing skill is always installed.
   - `proposals`: show each one to the user as its name, `compare_url`, `changed_files` and `instruction_files_changed` (true means a skill's instruction text changed, so read the diff before saying yes; `null` means unknown, so open the repo or compare link before saying yes), then ask once per skill: `Apply the <name> update to <short sha>? (yes / no)`. Only on an explicit yes run `skills-check.py <repo> --fix --apply-update <name>=<sha>`; its `applied` list confirms what moved. On no, leave it. Headless or under autopilot, never apply: add a Decisions action item with the `apply` command from the proposal.
   - `update_skipped`: a non-null value is the reason the daily proposal sweep did not run (`skills-lock.json` under 24h old); print it as one line and continue.
   - Append each `lesson_candidates` line to `.harness/lessons-inbox.md`. `a package launcher` not `ok` → print `Skills pre-check incomplete: a package launcher <state>.` and continue. None of these block the run.

**Resume mode.** If the request is `run resume`, read `.harness/handoff/latest.md` first (if it is missing, run `python3 "$PLUGIN/scripts/dt_gate.py" bridge handoff-write.py <repo>` to build it). Print its `## State`, `## Open items` and `## Next action`, then ask once: `Continue with the next action? (y/n)`. On yes: if the next action is a `run add secret NAME` command, go to **Add secret mode**; if it says `Checkpoint pending: plan checkpoint`, show the run's plan and resume at the **Plan checkpoint**; if it says `Checkpoint pending: ship checkpoint` or that the latest receipt is not approved, show that receipt and resume at the **Ship checkpoint**; if it says there are no open items, ask `What is the next task?`; otherwise run the pipeline below with the next action as the task. On no, stop. Open action items can be listed or changed with `/dt-action-items`.
**First contact (code-review, once per repo).** If the repo has no `.harness/` directory, the harness has never been in it. Before anything else, install and run `the publisher's installer for https://github.com/mattpocock/skills --skill code-review` (see Companion skills in `.harness/discipline.md`) on the repo and show its findings, then write the marker: `mkdir -p .harness && date +%F > .harness/seen`. The marker is the `.harness/` directory itself, so the next run or setup in the same repo does not re-trigger; this fires once per repo, on first contact only.
**Run-trigger check-in (loop-me).** When `/dt-run` is triggered, before dispatching any builder, install and run `the publisher's installer for https://github.com/mattpocock/skills --skill loop-me` (see Companion skills in `.harness/discipline.md`) and use it to check in with the user on the task and what they expect; fold what they say into the task text.
0. **Scope.** Run `python3 "$PLUGIN/scripts/dt_gate.py" bridge scope-check.py .`. `workspace-member` → say exactly `Pivot: <repo> belongs to workspace <root>; running in workspace mode from <root>.` and use the workspace root for every later path; `none` → run `/dt-setup` first; otherwise continue. If `.harness/keep.yaml` exists at the effective root, read it: for each skill listed with source `the publisher's installer for <ref>` that is not on disk (`.claude/skills/<name>`, `~/.claude/skills/<name>`), add its install command to `.harness/action-items.md` → `## Decisions` as an action item instead of failing.
1. **Harness change.** If the request names a harness skill, agent, hook, or profile (a dts2-harness file, not the repo's own code), print `That changes the harness itself; use `/dt-evolve`.` and stop. Never plan a harness change as a repo task.
2. **Config and mode.** Look for `.harness/config.yaml` in the repo, then `.harness-workspace.yaml` in a parent folder. Neither → stop and point to `/dt-setup`. Print one mode line: `Mode: workspace` if `.harness-workspace.yaml` was found, else `Mode: single`.
3. **Ignore guard.** For each repo involved: `python3 "$PLUGIN/scripts/dt_gate.py" bridge ensure-ignored.py <repo>`.
4. **End state.** If `.harness/config.yaml` exists and `.harness/end-state.md` does not, print exactly `No end state yet; /dt-setup interviews to one.` and continue.
   **Planned deploy.** If `.harness/end-state.md` has `deploy.status: planned`, say `Production target is planned but not built yet; building it first.` and run this pipeline on the task `Build the production target: <deploy.plan>` (both checkpoints apply). Then ask once: `Continue with your task now? (y/n)`
5. **Settings.** Read `.claude/dts2-harness.local.md`: `auto_scale` (default true), `max_builders` (4), `max_reviewers` (4), `second_opinion` (none), `auto_learn` (true), `continuous_dispatch` (true), `builder_timeout_min` (20). Read-only seats (reviewers, scouts, verifiers) may fan out wider than writers: `max_builders` caps the seats that write files, not the seats that only read.
6. **Roster.** `python3 "$PLUGIN/scripts/dt_gate.py" bridge roster.py resolve --config .harness/config.yaml`. On error, show it and stop. Keep the JSON. Then make sure every enabled agent has its project memory file before any builder is dispatched: `python3 "$PLUGIN/scripts/dt_gate.py" bridge agent-memory.py --write <repo> --agents <enabled agents, comma-separated>` (idempotent: it creates a missing file, only appends a managed block to an existing one, and never overwrites user content).
7. **Clean tree.** `git status --porcelain` in every repo involved. If dirty, ask once: stash and restore after, build on top, or stop. Record `git rev-parse HEAD` per repo as the rollback point and pin it as a ref with `python3 "$PLUGIN/scripts/dt_gate.py" bridge rollback_ref.py create --stamp <stamp> --repo <repo>` (`refs/dts2/<stamp>/base`); an existing ref at another commit is never moved. Pass that ref as `--base` to the checks, review split and findings digest.
   **Run branch.** In each git repo, take the run stamp (`date +%Y%m%d-%H%M%S`), create `dts2/<stamp>/main` from the current branch with `git switch -c dts2/<stamp>/main`, and record the stamp and branch in `.harness/runs/<stamp>/state.md`. Reuse that stamp for the rest of the run. Non-git folders have no run branch.
8. If the task is under 10 words or vague, ask one clarifying question.
9. Production deploys, data deletion, auth, or payments → confirm before anything else.

## Guardrails
- Context guard: a spike before the plan checkpoint stops the run and re-runs setup; never push through it.
- Both checkpoints need a human. Headless runs stop at each and write what a human would have seen.
- One writer per file across all builders.
- Never idle while a ready, non-conflicting section exists; never dispatch two builders onto overlapping files to avoid idling.
- Never write `do_not_touch` paths. Never push, deploy, or merge to main.
- Never ask for, print, or log a secret's value.
- Fix rounds cap at 3; escalations go to `.harness/state.md`.
- Every dispatch names a model and an effort (Rule 9.2). A builder never runs a frontier model.
- Rulings go to state.md as `Ruling: <what> — <why> — <cost if wrong>`.
