---
name: model
description: Choose which agent provider acts as the orchestration lead, so the lead, advisory and sign-off seats run on it instead of the default Claude. Detects the installed agents, lists the ones able to give advice, asks the user to pick, and records lead_provider in the project settings. Builders are unaffected and always run the cheapest capable model. Use when the user says switch the lead, change the orchestrator, use Codex or Gemini as lead, or pick the main model provider.
---

# Model — pick the orchestration provider

Frontier-tier seats (lead planning, advisory review, sign-off) default to Claude. This skill switches which provider fills them. Execution seats are never affected: builders keep running the cheapest capable model at a complexity-scaled effort, resolved by `scripts/delegate.py`, whichever provider leads. The rule that frontier is only for advice and sign-off holds for every provider.

## Steps
1. **Detect.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" detect --project .` lists the installed agents.
2. **Eligible providers.** The installed agents whose profile roles include `reviewer` or `second-opinion` (the `lead_eligible` rule in `scripts/delegate.py`). Show each with its models: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" model --agent <name> --tier frontier`.
3. **Ask once** which provider should lead, naming the current value of `lead_provider` (default `claude`). If only Claude is installed, say so and stop.
4. **Write it.** Set `lead_provider: <name>` in `.claude/dts2-harness.local.md` frontmatter (add the line if absent, replace it if present), or in the project's `.harness/` settings when that is where the project keeps them. Change nothing else in the file.
5. **Confirm** in one line: `Lead provider: <name>. Builders still run the cheapest capable model.`

## Notes
- A stalled lead fails over to the next eligible provider automatically (`scripts/failover.py`); the handoff file is the same one `/dts2-harness:upgrade` uses.
- Restart Claude Code after editing so hooks pick up the setting.
- A provider outside the eligible list is ignored and Claude is used instead.
