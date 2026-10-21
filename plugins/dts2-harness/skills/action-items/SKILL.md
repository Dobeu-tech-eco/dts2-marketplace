---
name: action-items
description: Show the open action items for this repo grouped as Secrets, Decisions, Handoff, Deploy and Promotions, each with its age, owner and the exact command that resolves it, and mark items done, add items, or assign an owner. Use when the user asks what is left for them, what is blocked on them, what the open action items are, or says action items, to-do, what do I still owe, mark that done, or hand this to another agent.
---

# Action items — what is still open and who owns it

Reads `.harness/action-items.md`; handoff briefs under `.harness/handoff/` appear as Handoff rows. All reading and writing goes through `scripts/action-items.py`; never edit the table by hand.

## List (default)
1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/action-items.py" <repo> list`. In workspace mode, run it per repo.
2. Print the items grouped in this order: Secrets, Decisions, Handoff, Deploy, Promotions. One line each: `<id> <item> — owner <owner or unassigned>, <age_days>d — <resolve_command>`. Skip empty groups. No open items → say `No open action items.`
3. Row ids are the group letter plus the row position: `S1` secret, `D1` decision, `H1` handoff, `Y1` deploy, `P1` promotion. Ids stay stable when rows are marked done.
4. `resolve_command` is what the user runs next:
   - Secrets → `run add secret NAME` (`/dts2-harness:run add secret NAME`)
   - Promotions → `learn promote <id>` (`/dts2-harness:learn`)
   - Handoff → `open .harness/handoff/<agent>/<n>.md`
   - Deploy and Decisions → `run` (deploy watch and plan checkpoint respectively)

## Subcommands
- `done <row>`: `action-items.py <repo> done S1`. Marks the row `done`. For a secret, check presence first as in `/dts2-harness:run` (`add secret NAME`); never mark a secret done without it.
- `add <group> <text>`: `action-items.py <repo> add Decisions "pick a domain"`. Appends an open row with today's date and prints its id. For Secrets the text is the variable name.
- `assign <row> <agent>`: `action-items.py <repo> assign S1 codex`. Sets the owner column. The owner is the agent or person who acts next.

After `done`, `add` or `assign`, refresh the pass-off file: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" <repo>`.

## Guardrails
- For secrets, never print a value: names, status and commands only. Text that looks like `NAME=value` is redacted by the script.
- Only the user marks Decisions done; an agent assigns or adds but never decides for them.
- Never edit `.env`, push, or run a resolve command for the user. Print it.
