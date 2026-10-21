---
name: evolve
description: Change the dts2 harness itself — edit a skill, agent, hook, script, profile, or template in the dts2-marketplace source repo, validate, test, bump both manifest versions, and commit; push only on an explicit yes. Use when the user says evolve, improve the harness, add an agent profile, fix a dts2 skill, or add a lesson-driven change to the plugin itself.
---

# Evolve — change the harness at its source

Never edit the installed copy. `plugins/cache` and `plugins/synced` are generated; edits there are lost on the next update and are never made.

## `evolve deploy`
This mode changes the current repo's deploy target, not the plugin. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/deploy-detect.py" <repo>`, ask the setup skill's Deploy target question, and rewrite the `deploy:` block in `.harness/end-state.md`. Skip sections 1–6.

## 1. Locate the source
1. `git remote -v | grep dts2-marketplace` in the current directory. Match → use this checkout.
2. Else `~/.dts2/marketplace` if it exists.
3. Else `git clone https://github.com/Dobeu-tech-eco/dts2-marketplace.git ~/.dts2/marketplace`.
State which checkout you are using. Work on a branch, not the default branch.

## 2. Make the change
Edit under `plugins/dts2-harness/`. Add or change a test first when behavior or required text changes. Keep one concern per change.

## 3. Validate and test
Run all three; stop on any failure and fix before continuing:
- `claude plugin validate plugins/dts2-harness`
- `claude plugin validate .`
- `python3 -m unittest discover -s plugins/dts2-harness/tests`

## 4. Bump versions
Bump both manifests (`plugins/dts2-harness/.claude-plugin/plugin.json` and the marketplace entry) to the same version:
- patch for text-only changes
- minor for a new skill, agent, or script
- major for a checkpoint or layout change

## 5. Commit, then push only on a yes
Commit with a message that names the change and the bump. Push only after the user gives an explicit yes; silence or a vague reply means do not push. The change reaches other machines only once it is on the repo's default branch; after the push, open a PR or merge on a second explicit yes, and say the update command picks it up after that.

## 6. Tell the user how to pick it up
Print `/plugin marketplace update dts2`, then tell the user to restart Claude Code so the new version loads.
