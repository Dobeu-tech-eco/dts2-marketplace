---
name: dt-action-items
description: "Run the /dt-action-items procedure shipped in this plugin. Show open action items (Secrets, Decisions, Handoff, Deploy, Promotions) with age, owner and resolving command; mark done, add, or assign. Use when asked what is left, what is blocked on me, action items, or to hand th..."
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-action-items/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Action items — what is still open and who owns it

Reads `.harness/action-items.md`; handoff briefs under `.harness/handoff/` appear as Handoff rows. All reading and writing goes through `scripts/action-items.py`; never edit the table by hand.

## List (default)
1. Run `python3 "$PLUGIN/scripts/dt_gate.py" bridge action-items.py <repo> list`. In workspace mode, run it per repo.
2. Print the items grouped in this order: Secrets, Decisions, Handoff, Deploy, Promotions. One line each: `<id> <item> — owner <owner or unassigned>, <age_days>d — <resolve_command>`. Skip empty groups. No open items → say `No open action items.`
3. Row ids are the group letter plus the row position: `S1` secret, `D1` decision, `H1` handoff, `Y1` deploy, `P1` promotion. Ids stay stable when rows are marked done.
4. `resolve_command` is what the user runs next:
   - Secrets → `run add secret NAME` (`/dt-run add secret NAME`)
   - Promotions → `learn promote <id>` (`/dt-learn`)
   - Handoff → `open .harness/handoff/<agent>/<n>.md`
   - Deploy and Decisions → `run` (deploy watch and plan checkpoint respectively)

## Parked sections
Sections the run parked appear after the groups: the list also shows every `## Sections` row of `.harness/end-state.md` with status `blocked`, one line each: `section <#> <name> — blocked (<action-item id>)`. The same lines appear in the handoff file's `## Open items`.

## Subcommands
- `done <row>`: `action-items.py <repo> done S1`. Marks the row `done`. For a secret, check presence first as in `/dt-run` (`add secret NAME`); never mark a secret done without it.
- `add <group> <text>`: `action-items.py <repo> add Decisions "pick a domain"`. Appends an open row with today's date and prints its id. For Secrets the text is the variable name.
- `assign <row> <agent>`: `action-items.py <repo> assign S1 codex`. Sets the owner column. The owner is the agent or person who acts next.

After `done`, `add` or `assign`, refresh the pass-off file: `python3 "$PLUGIN/scripts/dt_gate.py" bridge handoff-write.py <repo>`.

## Guardrails
- For secrets, never print a value: names, status and commands only. Text that looks like `NAME=value` is redacted by the script.
- Only the user marks Decisions done; an agent assigns or adds but never decides for them.
- Never edit `.env`, push, or run a resolve command for the user. Print it.
