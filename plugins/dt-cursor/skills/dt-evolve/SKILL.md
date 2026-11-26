---
name: dt-evolve
description: "Change the dts2 harness itself in its source repo: edit a skill, agent, hook, script, profile or template, validate, test, bump versions, commit; push only on an explicit yes. Use for evolve, improve the harness, or fix a dts2 skill."
disable-model-invocation: true
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-evolve/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Evolve — change the harness at its source

Never edit the installed copy. `plugins/cache` and `plugins/synced` are generated; edits there are lost on the next update and are never made.

## `evolve deploy`
This mode changes the current repo's deploy target, not the plugin. Run `python3 "$PLUGIN/scripts/dt_gate.py" bridge deploy-detect.py <repo>`, ask the setup skill's Deploy target question, and rewrite the `deploy:` block in `.harness/end-state.md`. Skip sections 1–6.

## Harness lessons
The run skill invokes this mode automatically after every ship (and the plan checkpoint shows the pending count), so the user does not have to remember `/dt-evolve`. When run without a specific change, read `.harness/harness-lessons.md` in the current repo (written by `learn` from `harness:` lessons). Offer each open lesson as a plugin change: quote the line, propose the edit under `plugins/dts2-runtime/`, and run sections 1–6 for it. Change nothing until the user gives an explicit yes for that lesson. On an explicit yes and a finished change, mark the line `done` with the commit; on a no, mark it `dropped`.

## 1. Locate the source
1. `git remote -v | grep dts2-marketplace` in the current directory. Match → use this checkout.
2. Else `~/.dts2/marketplace` if it exists.
3. Else clone the marketplace named by the `repository` field of `$PLUGIN/.claude-plugin/plugin.json` (or `git remote get-url origin` of the installed plugin's checkout): `git clone <that url> ~/.dts2/marketplace`. If neither names one, ask the user for the URL; never guess an org.
State which checkout you are using. Work on a branch, not the default branch.

## 2. Make the change
Climb the hardening ladder: when a lesson or failure asks for a rule, first propose a hook, then a test, then a check in `checks.sh` or `scripts/`; write prose in a skill only when none of those can enforce it, and say in the proposal why. Edit under `plugins/dts2-runtime/`. Add or change a test first when behavior or required text changes. Keep one concern per change. The directory listing is generated from this tree: run `python3 plugins/dts2-runtime/scripts/directory_edition.py` after a change it publishes, and commit `plugins/dts2-harness` with it.

## 3. Validate and test
Run all three; stop on any failure and fix before continuing:
- `claude plugin validate plugins/dts2-runtime`
- `claude plugin validate plugins/dts2-harness`
- `claude plugin validate .`
- `python3 -m unittest discover -s plugins/dts2-runtime/tests`
- `python3 plugins/dts2-runtime/scripts/directory_edition.py --check`
- `python3 plugins/dts2-runtime/scripts/cursor_surface.py --check`

## 4. Bump versions
Run `python3 plugins/dts2-runtime/scripts/bump-version.py <x.y.z>` (it writes every place the runtime version is recorded, including both manifests, and `--check` verifies them) instead of editing the manifests by hand. The directory listing version lives in `plugins/dts2-runtime/scripts/directory_edition.py`. Choose the version:
- patch for text-only changes
- minor for a new skill, agent, or script
- major for a checkpoint or layout change

Record the change as a bullet in a `changelog.d/batch-<n>.md` fragment; `scripts/changelog-join.py --apply` moves the fragments under `## Unreleased` in the README at release.

## 5. Commit, then push only on a yes
Commit with a message that names the change and the bump. Push only after the user gives an explicit yes; silence or a vague reply means do not push. The change reaches other machines only once it is on the repo's default branch; after the push, open a PR or merge on a second explicit yes, and say the update command picks it up after that.

## 6. Tell the user how to pick it up
Print `/plugin marketplace update dts2`, then tell the user to restart Claude Code so the new version loads.
