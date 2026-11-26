---
name: dt-cooldown
description: "Pause an agent that hit a usage limit until its reset date, resume it, or list what is paused. Use for set a cooldown, agent is out of usage, clear a cooldown, or which agents are paused."
disable-model-invocation: true
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-cooldown/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Cooldown — pause an agent until its usage limit resets

Usage limits belong to the account, so one status file (`~/.dts2/agent-status.json`, or the path in `DTS2_AGENT_STATUS`) is shared by every session on the machine. The roster probe, the lead failover and the SessionStart hook all read it. A paused agent is never called, probed or picked as lead until its reset time passes; it then comes back on its own.

All commands: `python3 "$PLUGIN/scripts/dt_gate.py" bridge cooldowns.py <command>`.

## Steps
1. **set** `set <agent> <date or duration> [reason]`
   - A duration such as `2d 3h` runs `set <agent> --in "2d 3h" --reason "<reason>"`.
   - A date or time such as `2026-11-21`, `Nov 21 9:00 AM` or an ISO timestamp runs `set <agent> --until "<date>" --reason "<reason>"`.
   - A date that cannot be read exits 2: ask for another form once.
2. **clear** `clear <agent>` removes the pause now (the limit was lifted early, or the date was wrong).
3. **list** `list` shows the agents paused now with their reset time and reason; `list --all` also shows entries that have ended.
4. **Confirm** in one line: which agent is paused, until when (local time and UTC), and that it is skipped everywhere until then.

## First agent to hit a limit
When a dispatch or a call fails with a usage, quota or rate-limit message:
1. Pipe the output to `detect --agent <agent> --exit-code <n> --record`.
2. If the result says `"limited": false`, this is not a usage limit; handle it as an ordinary failure.
3. If it says `needs_date: true`, ask the user ONCE for the reset date or duration, then run `set <agent> --until "<date>" --source user`. A provisional pause of about five hours stays in place until they answer.
4. Tell the user which agent is paused and until when, then continue the work with the remaining agents.
5. Never re-probe or re-call a cooling agent. `check <agent>` exits 3 while it is paused; do not try to "see if it is back".

## Notes
- A limit that resets in under 15 minutes is not recorded; wait and retry instead.
- A later, shorter detection never shortens a pause that is already active; only `set` (a person's word) does.
- The SessionStart hook prints which agents are paused, and which came back, at the start of each session.
