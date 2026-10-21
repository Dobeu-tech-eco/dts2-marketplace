---
name: machine-prep
description: Scan this computer's agent tooling (Claude Code marketplace plugins, plugins synced from the claude.ai account, agents, skills, CLAUDE.md, Codex, Cursor, MCP servers), compare it to the agent-startup-blueprint profile, prune by disabling everything outside the keep-set, and set up the slim startup. Works on Windows, WSL, Linux, and macOS. Use when the user wants to clean up, slim down, pare down plugins, stop disabled plugins from coming back, audit context budget, set up a new machine, or apply the blueprint.
---

# Machine prep — scan, prune, set up

Follows the agent-startup-blueprint rules. Prune means disable, never delete. Credentials are never read or printed.

Python: use `python3`; on Windows try `python` then `py -3`.

## 1. Detect the environment
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/env-detect.py"`.
- If `wsl` is true and `claudeWrapsWindows` is true, the live Claude home is the Windows one. Run later steps with `--claude-home /mnt/c/Users/<user>/.claude`, or run them from Windows. Tell the user which home you are changing.
- Never sync or copy agents, skills, plugins, or rules between the Windows and WSL homes.

## 2. Audit (read-only)
Dispatch the `dts2-harness:auditor` agent, or run:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/machine-prep.py" audit [--profile <path>] [--claude-home <path>]`
The profile defaults to the plugin's `profiles/blueprint.json`. A `profile` value in `.claude/dts2-harness.local.md` overrides it.

Show the user: enabled plugins vs the keep-set, budget overruns, forbidden symlinks or sync scripts, and what is missing from the keep-set.

Then explain where plugins are coming from, because this is why disabled plugins come back:
- `syncedPluginsLoading` — plugins enabled on the user's claude.ai account. Claude Code re-downloads them into `~/.claude/plugins/synced/` at every session start and loads them as `<name>@synced`. New ones arrive enabled. This is usually the bulk of the context cost.
- `syncedRequiredByOrg` — synced plugins the organization marks required. Only a claude.ai admin can turn these off; say so.
- `projectEnablesOverridingYou` — plugins the current repo's `.claude/settings.json` enables, which beats the user setting. Fix per repo with `claude plugin disable <id> --scope local`.

Then report agents in two separate counts, because the blueprint's 4-agent rule covers only one of them:
- `claudeUserAgents` — files in `~/.claude/agents/`. This is the blueprint's 4-agent budget. These never sync to or from claude.ai.
- `claudePluginAgents` and `pluginAgentsBySource` — agents that come inside enabled plugins, including every synced plugin. claude.ai has no separate agent sync; agents arrive only inside plugins, so turning off `syncClaudeAiPlugins` (or disabling the synced plugin) removes them. Budget is 6, which is exactly dts2-harness's own team (lead, builder, reviewer, verifier, scout, auditor). Name the top sources so the user sees which plugins cost the most.
- `syncClaudeAiSkills` and `syncedSkillsOnDisk` — claude.ai skills sync separately from plugins into `~/.claude/skills/synced/`. Report only; turning it off also removes always-synced skills such as pdf and xlsx, so leave that choice to the user (`"syncClaudeAiSkills": false` in user settings).

## 3. Pick a tier
Run `... machine-prep.py plan --tier <light|standard|strict>` for each tier the user is weighing and show the exact diff. Without `--tier` the profile's `claude.defaultTier` (standard) is used. `--days N` sets the usage window (default 30). Show the three tiers in one table:

| Tier | Stays on | Goes off | For |
|---|---|---|---|
| light | Everything used in the window, the profile keep-set, `syncClaudeAiPlugins` and `syncClaudeAiSkills` untouched | Plugins with zero use in the window (not org-required) | Someone who wants no surprises |
| standard | Profile keep-set, the top `keepSyncedTopN` (5) used synced plugins, `keepSyncedPlugins` | Marketplace plugins outside the keep-set, all other synced plugins | Most people; the default |
| strict | Profile keep-set only | `syncClaudeAiPlugins: false`, `syncClaudeAiSkills: false`, everything outside the keep-set | A minimal, fast, predictable start |

Then present, from the audit inventory:
- `redundantAgentPacks` as one line per group: "keep `<keep>`, disable N" (these plugins ship the same agent files, so you pay for them N times).
- `duplicateSkillNames` as "skill X exists in A, B" so the user sees name collisions.
- The top 10 entries of `usage` (plugin -> calls in the window), so the choice rests on what they actually use.
- The `requiredByHarness` keep. Plugins matching the profile's `requiredByHarness` patterns (for example `marketing-skills@synced`, `impeccable@*`) are never disabled in any tier; the plan prints `(requiredByHarness)` on their line. Say why: the harness's own skills depend on them. Note that under strict, with `syncClaudeAiPlugins` off, a required synced plugin stays enabled in settings but claude.ai will not re-sync it.

Plugins added on claude.ai later arrive enabled in light and standard, so re-run the plan after adding some. Also list, as manual steps the script does not perform:
- Extra files in `~/.claude/agents` beyond the budget (suggest moving them to an archive folder).
- Global MCP servers that belong in one project.
- Codex plugin flags above budget.

Then ask once which tier to apply.

## 4. Approval gate
Ask once: apply the plugin change, apply and also walk through the manual steps, or stop. Do nothing without a yes.

## 5. Apply
Run `... machine-prep.py apply --tier <chosen>`. It backs up `settings.json` to `<claude home>/backups/` before writing. Report the backup path.

## 6. Set up the slim startup
- Confirm `dts2-harness@dts2` is enabled and `harness@harness` is disabled, so agents are not duplicated.
- Point the user to the blueprint repo's `apply.ps1` (Windows) or `apply.sh` (WSL/Linux) for Codex agents and the weekly budget audit, if they want those too.
- Remind them to restart Claude Code and to sign in with `claude auth login` on the binary they actually run.

## Guardrails
- Never uninstall. Uninstall only if the user names the plugin and says uninstall.
- Never edit `.claude.json`, `auth.json`, or any credential file.
- Never write API keys.
