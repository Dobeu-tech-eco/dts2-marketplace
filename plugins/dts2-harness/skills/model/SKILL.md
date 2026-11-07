---
name: model
description: Choose which agent provider fills the lead, advisory and sign-off seats; detects installed agents, asks the user to pick, and records lead_provider. Builders are unaffected. Use for switch the lead, change the orchestrator, or Codex or Gemini as lead.
disable-model-invocation: true
---

# Model — pick the orchestration provider

Frontier-tier seats (lead planning, advisory review, sign-off) default to Claude. This skill switches which provider fills them. Execution seats are never affected: builders keep running the cheapest capable model at a complexity-scaled effort, resolved by `scripts/delegate.py`, whichever provider leads. The rule that frontier is only for advice and sign-off holds for every provider.

## Steps
1. **Detect.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" detect --project .` lists the installed agents.
2. **Eligible providers.** The installed agents whose profile roles include `reviewer` or `second-opinion` (the `lead_eligible` rule in `scripts/delegate.py`). Show each with its models: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" model --agent <name> --tier frontier`.
3. **Ask once** which provider should lead, naming the current value of `lead_provider` (default `claude`). If only Claude is installed, say so and stop.
4. **Write it.** Set `lead_provider: <name>` in `.claude/dts2-harness.local.md` frontmatter (add the line if absent, replace it if present), or in the project's `.harness/` settings when that is where the project keeps them. Change nothing else in the file.
5. **Replicate skills when the lead changes.** The new lead must be able to run the same skills as the orchestrator, including the current `dt@dts2` plugin. A non-lead may still be on an older `dts2-harness` install. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lead_skills.py" sync --agents <name> --home "$HOME"`. That writes the current plugin and skill list into that agent's backend (`~/.codex` for Codex, `~/.dts2/agent-plugins/<name>` for every other agent) and turns off `dts2-harness@dts2` and `dts2@dts2`. Do not ask. Skip this step when the new lead is `claude`.
6. **Confirm** in one line: `Lead provider: <name>. Builders still run the cheapest capable model.` Tell the user to start a new session of that agent so it loads `/dt` instead of `/dts2-harness`.

## Notes
- A stalled lead fails over to the next eligible provider automatically (`scripts/failover.py`); the handoff file is the same one the run Pre-check writes before an upgrade.
- Restart Claude Code after editing so hooks pick up the setting.
- A provider outside the eligible list is ignored and Claude is used instead.

## Add or rename an agent
Use this when the user wants a second agent on the same provider, such as `grok` on the subscription plus `grok-api` on a pay-as-you-go key. Lead-provider steps above are unchanged.
1. **Pick provider and auth.** Provider is any profile from `roster.py list` (the base); auth is `subscription` or `api-key`.
2. **Show the suggested name:** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" suggest-name --base <provider>` (the base name when free, else `<base>-api`, `<base>-api-2`, ...). Let the user type another. Names are lowercase kebab-case, 2-32 characters, and not a role or tier word (lead, builder, reviewer, verifier, scout, auditor, fixer, all, none, frontier, standard, economy).
3. **Collision.** `roster.py add` exits 2 and names the layer (bundled, user or project) that already has the name. Say which layer, suggest `<name>-2`, and ask again. Never overwrite unless the user picks "edit existing", then pass `--edit-existing`.
4. **Key.** For `api-key`, tell the user to store the key in the system keyring, 1Password (`op`) or Doppler, and give only the reference: `keyring:dts2/<name>`, `op://vault/item/field`, `doppler:PROJECT/CONFIG/NAME` or `env:VAR`. Never ask for or write a raw key.
5. **Write it:** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" add --name <name> --extends <provider> [--auth api-key --api-key-ref <ref>] [--scope project|user] [--display-name X] [--roles a,b]`. It writes the profile (`.harness/agents/` or `~/.dts2/agents/`) and appends the roster entry; only the reference is stored.
6. **Rules (api-key agents only).** Show the defaults and let the user change them with "Edit agent rules" below: read-only, tasks review, docs and research, tier at most standard, $0.50 a run, $5 a day. deploy, merge, release, secrets and delete stay denied whatever they pick.
7. **Rename** with `roster.py rename <old> <new>`; it rewrites the profile, roster entries, and other profiles' `extends` and `fallback` in one step. Bundled profiles cannot be renamed.

## Edit agent rules
Use this to change what an agent may be called for. Run `roster.py rules <name> --show` and print the `written` and `effective` rules, so each question below names its current value. Ask them together, one line each, and change only what the user answers:
1. Tasks it may do (`allow_tasks`) and may not do (`deny_tasks`), from: review, build, test, docs, research, deploy, merge, release, secrets, delete, infra.
2. Highest model tier (`max_tier`): economy, standard or frontier.
3. Paths it must never touch (`paths_deny`), such as `**/.env*`, `infra/**`.
4. Read-only (`read_only`) and no secrets (`no_secrets`): yes or no.
5. Dollar caps per run and per day (`max_cost_usd_per_run`, `max_cost_usd_per_day`).

Then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" rules <name> --set key=value [--set ...]` (lists are comma-separated; exit 2 prints what to fix). `--reset` removes the block. Report the `warnings` from the output: for an API-key agent deploy, merge, release, secrets and delete stay denied even if allowed. A subscription agent has no rules unless you add some.
