# run — Phase 0, size and budget

## Phase 0 — Size and Budget check
1. Dispatch `dt:scout` (`model: haiku`) with the repo path(s) and the task. Use its tier unless `auto_scale` is false (then tier S).
   A scout report whose first line is `PARTIAL: hit turn cap at <step>` gives no tier: re-dispatch the scout with a narrower scope or a fresh agent, inside the fix-loop cap.
2. **Budget check** (`roster.py probe`). Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" probe --config .harness/config.yaml`. From its JSON:
   - Drop every agent in `dropped` for this run; keep its `reason`.
   - An agent with budget `low` keeps only the `second-opinion` role (the probe already restricts its `roles`); never give it a builder or reviewer seat.
   - Keep the probe JSON for the lead. Each agent carries `costTier` (1 cheapest).
   - Auth: each probe entry carries `auth` (`subscription`, `api-key`, `installed (unverified)` or `none`). Agents already logged in via subscription are used as-is; never prompt for a second authentication or an API key. An agent is dispatched via API key only when its roster entry says `auth: api-key` and `included: true`.
   - Claude is always usable for this run (it is running this skill); if the probe drops `claude`, keep it and show the reason as a one-line warning.
3. Resolve models once per agent you may use: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" model --agent <name> --tier <economy|standard|frontier>`. `null` means use that agent's default model. `delegate.py` is the source for a builder's model and effort (Phase 2); `roster.py model` stays the source for the advisory and sign-off tiers.
