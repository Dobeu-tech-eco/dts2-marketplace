---
name: upgrade
description: Upgrade the dts2 harness in place with one command. Writes the pass-off handoff and records the installed version, tells the user to update the marketplace and plugin, verifies the version actually advanced, then re-runs the harness end to end from the handoff. Use when the user says upgrade the harness, update dts2, get the latest dts2-harness, or asks to pick up a new release without losing their place.
---

# Upgrade — handoff, update, verify, resume

The agent cannot run `/plugin` itself: the user runs those slash commands. Everything else here is done by the agent.

## Re-entry check
If `.harness/upgrade-from.txt` already exists, a previous upgrade was started and the session was probably restarted to load the new version. Run step 3 first. `advanced: true` → go straight to step 4. `same: true` → the update has not landed; continue at step 2. Never overwrite an existing `upgrade-from.txt` in step 1.

## 1. Handoff first
1. Create `.harness/` if it is absent.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" <repo>` to write the current project and harness state to `.harness/handoff/latest.md`.
3. Record the installed version: read `version` from `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` and write it as one line to `.harness/upgrade-from.txt`.

## 2. Update the marketplace and the plugin
Tell the user, plainly, to run these two commands themselves (the agent cannot run `/plugin`):
```
/plugin marketplace update dts2
/plugin install dts2-harness@dts2
```
or to confirm the update prompt if Claude Code shows one. Then ask them to reload plugins or restart Claude Code so the new version loads, and to say `done`. Wait for it.

## 3. Verify it updated
After the user confirms, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/upgrade-check.py" --from-file .harness/upgrade-from.txt`. It prints JSON `{"from","to","advanced","same"}`.
- `advanced: true` → go to step 4.
- Otherwise say `The update did not take: still on <to>.` and stop. Do not re-run anything. The user can retry the two commands and call `/dts2-harness:upgrade` again.

## 4. Re-run end to end
1. Read `.harness/handoff/latest.md` back (its `## State`, `## Open items` and `## Next action`).
2. Continue with `/dts2-harness:run resume`, or with `/dts2-harness:setup` when `scope-check.py` reports no harness here or the context-guard rules say setup was not done.
3. Delete `.harness/upgrade-from.txt` so the next upgrade starts clean.
4. Print one line: `Upgraded <from> -> <to>; resuming: <next action>.`

## Guardrails
- Handoff first, always; never start the update without `latest.md` and `upgrade-from.txt` on disk.
- Never claim an upgrade succeeded without the `advanced: true` check.
- Never push, merge or edit the plugin cache. To change the harness's own source use `/dts2-harness:evolve`.
