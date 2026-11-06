---
name: fleet-checkin
description: Gather the check-in items from every harness session on this computer into one report, leading with what needs you, and ask every live session for a fresh check-in. Use for check in on all my sessions, what needs me across the fleet, or what are all my agents blocked on.
---

# Fleet check-in — one report from every session on this machine

`/dts2:check-in` reports one project against its end state. This skill collects the check-in items that sessions have recorded across the machine (via the fleet registry) into a single report. It is a sibling of `/dts2:fleet`; nothing is typed into any terminal.

All commands: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/fleet.py" <command>`.

## Steps
1. **Report** run `checkins [--since 24h]` and show it as printed. Lead with **Needs you** (blockers and questions), then the rest by session.
2. **Offer a refresh.** Say how many live sessions would be asked, then ask whether to request a fresh check-in from all of them. On a yes, run `broadcast --kind checkin --to all` (add `--to harness` to limit it to sessions with a harness). **Confirm first**; do not send without a yes.
3. **Re-run later.** Tell the user to run `checkins` again after a few minutes, or on their next visit; answers arrive as sessions are touched.
4. **Answering (what an agent in a session runs).** A session that receives a `checkin` broadcast replies with `checkin --session <id> --status <status> [other flags as `checkin --help` lists]`, for example `--status working`, `blocked` or `done`, with a short note and any question for the person. It then carries on with its work.

## Honest limits
- Sessions answer on their next prompt, tool call or stop. A session idle at the prompt answers only when it is next touched.
- A crashed session shows `stale` and will not answer; its last recorded items still appear.
- Only sessions with the plugin updated register. Per machine only.
- `checkins` is read-only; only the broadcast writes to the inbox.
