---
name: composio
description: Connect Composio so agents reach 1000+ apps through one connection, cache the toolkit map, and offer to disable plugins, MCP servers and skills Composio already covers. Use to set up Composio or trim overlapping tools.
disable-model-invocation: true
---

# Composio — one connection for app tools

Composio is a third-party tools integration. Memory stays in the knowledge store (`/dt:knowledge`), never in Composio. Credentials are never read, printed or pasted: the CLI keeps them in its own secure config (`~/.composio`). Prune means disable or archive with a backup, never delete.

All commands: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/composio-setup.py" <command>`. Each prints one JSON object. Exit 2 means a usage error or a missing binary; show the `hint`.

## 1. Account question
Ask exactly one yes/no question with AskUserQuestion: "Do you have a Composio account?"
- **No**: write one paragraph. Composio gives agents one authenticated connection to 1000+ apps (GitHub, Slack, Gmail, Notion, Linear and more), with search, parallel execution and a remote workbench, so you stop installing a separate plugin or MCP server per app. Give the signup link https://composio.dev. Run `composio-setup.py decide --account no` and stop.
- **Yes**: continue.

## 2. Status and install
Run `composio-setup.py status`. Report `cli`, `logged_in`, `plugin_enabled`, `mcp_servers`, `duplicate_connection` and the saved `decision`.
- If `duplicate_connection` is true, warn: the plugin and a hosted MCP server would run the same connections twice. Never keep both; ask which to disable.
- If the plugin or CLI is missing, ask once whether to proceed, then show these steps for the user to run (do not run installers silently):
  1. `/plugin marketplace add ComposioHQ/composio-plugin-cc`
  2. `/plugin install composio@composio`
  3. CLI: `curl -fsSL https://composio.dev/install | sh`
  4. `composio login` (opens a browser). The login is the user's own secure config in `~/.composio`; never paste keys into chat or into a repo file.
- MCP is the alternative only when the user asks: Composio Connect `https://connect.composio.dev/mcp` (add it with `claude mcp add`, then sign in through `/mcp` in the browser, or read a key from an environment variable; never a literal key in a file). Never run the plugin and MCP together.

## 3. Save the decision
Run `composio-setup.py decide --account yes --always-use --connection plugin` (use `mcp` or `cli` to match what the user chose). It writes `~/.dts2/composio.json`; no secrets go in it.

## 4. Map the catalogue
Run `composio-setup.py map` (full toolkit catalogue and connected accounts, saved to `~/.dts2/composio-tools.json`). If the CLI is unavailable but the Composio MCP meta-tools are, call `COMPOSIO_SEARCH_TOOLS` for the user's apps, save the result to a temp JSON file `{"toolkits": [...], "connected": [...]}` and run `map --from-json <file>`. Report the toolkit count and which are connected.

## 5. Find overlap
1. Run `composio-setup.py overlap` (add `--all` to cover every toolkit, not only connected ones).
2. Run the `/dt:machine-prep` flow's audit and plan (steps 2 and 3 of that skill) so the budget view and the Composio view agree.
3. Show one combined list: skills, plugins and MCP servers Composio already covers, each with kind, id, toolkit and scope, plus the `kept` entries and why (Composio itself, `dts2`, the blueprint `requiredByHarness` keep, `.harness/keep.yaml` plugins).

## 6. Approval gate
Ask once: disable the listed items, pick some, or stop. Nothing changes without a yes.
On yes run `composio-setup.py disable --ids a,b --dry-run`, show it, then run it without `--dry-run`. Report the `backups` paths, every `manual` step (for example `claude mcp remove <name> --scope user`) and the `skipped` ids. Skills move to `skills-archive`; plugins and MCP entries are switched off in settings after a timestamped backup. Never delete; to undo, restore the backup or move the folder back.

## 7. Routing rule (once `always_use` is true)
1. Check the cached tool map first (`~/.dts2/composio-tools.json`); search only when the toolkit is not in it.
2. Call `COMPOSIO_SEARCH_TOOLS` once per workflow with a session `generate_id`, and reuse the returned `session_id` for every later meta call.
3. Use `COMPOSIO_MULTI_EXECUTE_TOOL` for independent calls (up to 50 per call); run dependent calls in sequence.
4. Use `COMPOSIO_REMOTE_WORKBENCH` or `COMPOSIO_REMOTE_BASH_TOOL` for bulk, large or file-based results. Each call has a 180 s limit, so checkpoint to `/mnt/files/` between calls.
5. Never run the plugin and a hosted MCP server for Composio at the same time.
6. Memory stays with the knowledge store (`/dt:knowledge`); Composio is a tools integration only.

## Guardrails
- Never read, print, copy or write API keys or the `~/.composio` contents.
- Never delete files; disable or archive with a backup.
- Keep the reply under 200 words unless the user asks for detail.
