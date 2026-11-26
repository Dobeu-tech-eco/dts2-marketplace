---
name: dt-knowledge
description: "Run the /dt-knowledge procedure shipped in this plugin. Keep your own standing preferences, glossary terms (brands, product lines, repo groups) and cross-project learnings in a private store that follows you across devices. Use for remember this preference, what is my standard..."
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-knowledge/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Knowledge

For a Cloudflare knowledge store, use the remote MCP connection already configured by the user in Cursor. Use the connected knowledge tools to list, find, record or remove preferences, terms and learnings when the user requests it. Confirm removals with the user. Keep credentials out of knowledge entries and conversation.

For a local or synced folder, use a folder the user identifies. Store one Markdown entry per key under entries/preference, entries/term or entries/learning. Read the store only when the user invokes this skill.
