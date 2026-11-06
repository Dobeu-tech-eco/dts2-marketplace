---
name: fleet
description: See every harness session on this computer, read their status, logs and ledgers without interrupting them, and send one note, handoff, pause or knowledge finding to all of them. Use for list my sessions, what are all my harnesses doing, tell every session to hand off, or broadcast to all agents.
---

# Fleet — every harness session on this machine, and one message to all of them

Hooks register each session in a shared home (`DTS2_FLEET_HOME`, else `DTS2_HOME/fleet`, else `~/.dts2/fleet`). This skill reads that registry and writes to a broadcast inbox that each session picks up on its own. It never types into a terminal.

All commands: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/fleet.py" <command>`.

## When to use
- You run many sessions (for example in terminal tabs) and want one table of what each is doing.
- You want a session's recent turns, handoff or task ledger without opening its tab.
- An update or an incident means every session should stop cleanly, hand off, or hear a finding.

## Steps
1. **List** `list [--all] [--json]`: label or short id, repo@branch, state (`working`, `idle`, `ended`, `stale`), last seen, turns, pending broadcasts. `--all` includes ended sessions.
2. **Show** `show <ref> [--json]`: the registry entry plus that session's harness ledgers (handoff, task ledger tail, open intake items, lanes, cooldowns, incidents when present). `<ref>` is a unique session id prefix or a label.
3. **Logs** `logs <ref> [-n 20]`: the last N turns from the transcript, text only, tool calls cut to one line. Reads files only; safe while the session runs.
4. **Label** `label <ref> <name>` names a session (for example the tab name) so `<ref>` is easy to type.
5. **Broadcast** `broadcast --kind note|handoff|pause|knowledge|checkin --text T [--to all|harness|repo:X|id:X|label:X ...] [--expires 24h] [--from-knowledge KEY]`
   - `note`: read it. `handoff`: finish the current step, write the handoff, stop and say so. `pause`: stop after the current step and wait. `knowledge`: a finding to apply (use `--from-knowledge KEY` to take the text from the knowledge store). `checkin`: answer with a fresh check-in (see `/dts2:check-in all`).
   - **Confirm with the user first.** Run `list` (or `list --json`) filtered to the intended targets, tell the user how many live sessions match and the exact text and kind, and send only after a yes. A broadcast cannot be recalled once a session has read it.
6. **Status** `status [<id>]`: for a broadcast id (or all), which sessions have picked it up and which are still pending.
7. **Prune** `prune [--days 14]` removes ended session files older than the limit.
8. **Report** in a few lines: what was listed or sent, how many sessions it reached now, how many are pending.

For one report of every session's check-in items, use `/dts2:check-in all`; it runs `checkins [--since 24h] [--json]` and `checkin --session <id> --status "<text>" [--blocker X ...] [--next N] [--question Q ...]` (what a session runs to answer).

## Honest limits
- A session sitting idle at the prompt gets a broadcast on its next prompt, tool call or stop, not instantly. Claude Code cannot push input into an idle terminal. `status` shows those as pending so you know which tabs to touch.
- A session that crashed or was killed shows `stale` after 30 minutes with no heartbeat. The pid check marks it dead sooner on Linux and macOS and is skipped on Windows.
- Only sessions with the plugin updated and enabled register. A session started before the update registers on its next hook firing, not from history.
- Per machine only. Nothing crosses to another computer.
- Read-only views (`list`, `show`, `logs`, `status`) never touch a running session.
- Broadcast text is delivered as an operator note from this machine, with the same trust as the person's own typing.
