---
name: machine-prep
description: Scan this computer's agent tooling (Claude Code plugins, agents, skills, CLAUDE.md, Codex, Cursor, MCP servers), compare it to the agent-startup-blueprint profile, prune by disabling everything outside the keep-set, and set up the slim startup. Works on Windows, WSL, Linux, and macOS. Use when the user wants to clean up, slim down, pare down plugins, audit context budget, set up a new machine, or apply the blueprint.
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

## 3. Plan the prune
Run `... machine-prep.py plan` and show the exact `enabledPlugins` diff. Also list, as manual steps the script does not perform:
- Extra files in `~/.claude/agents` beyond the budget (suggest moving them to an archive folder).
- Global MCP servers that belong in one project.
- Codex plugin flags above budget.

## 4. Approval gate
Ask once: apply the plugin change, apply and also walk through the manual steps, or stop. Do nothing without a yes.

## 5. Apply
Run `... machine-prep.py apply`. It backs up `settings.json` to `<claude home>/backups/` before writing. Report the backup path.

## 6. Set up the slim startup
- Confirm `dts2-harness@dts2` is enabled and `harness@harness` is disabled, so agents are not duplicated.
- Point the user to the blueprint repo's `apply.ps1` (Windows) or `apply.sh` (WSL/Linux) for Codex agents and the weekly budget audit, if they want those too.
- Remind them to restart Claude Code and to sign in with `claude auth login` on the binary they actually run.

## Guardrails
- Never uninstall. Uninstall only if the user names the plugin and says uninstall.
- Never edit `.claude.json`, `auth.json`, or any credential file.
- Never write API keys.
