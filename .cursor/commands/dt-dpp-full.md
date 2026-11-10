---
name: dt-dpp-full
description: "Run the /dt-dpp-full procedure shipped in this plugin. dpp with --full. Adds a delegation scan and fills up to five lanes. Outside autopilot it asks before each new lane (dpp_full_ask_each_lane defaults true). Autopilot and fullauto skip that ask. Use when the user says dpp-fu..."
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-dpp-full/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# dpp-full — dpp with `--full`

Everything is `skills/dpp/SKILL.md`; run it with `--full`.
The only differences: the delegation scan joins the lane sources (section 1), and continuous dispatch starts the next eligible lane (section 5). Outside autopilot, section 8 asks before each new lane while `dpp_full_ask_each_lane` is true (the default). Autopilot and fullauto skip that ask.
It still stops at `pr-open` and never merges a `blocked` PR.
