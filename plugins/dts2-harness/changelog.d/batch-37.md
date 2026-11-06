### Added

- `/dts2:composio` skill (user only): asks once whether you have a Composio account, connects it (plugin by default), maps the toolkit catalogue and connected accounts, and offers to disable overlapping tools. Nothing is deleted.
- `scripts/composio-setup.py` with `status`, `decide`, `map`, `overlap` and `disable`; state lives in `~/.dts2/composio.json` and `~/.dts2/composio-tools.json`, credentials are never read.
- `onboard` gains an optional Composio step that records the yes or no answer.
- `machine-prep` lists plugins, MCP servers and skills that a connected Composio toolkit covers and offers to disable or archive them, with backups.
- `improve-scan.py` drops MCP recommendations (github, vercel, supabase, neon) that a connected Composio toolkit covers and reports them under `info` as "covered by Composio (<toolkit>)"; `find-skills` prefers Composio toolkits over duplicate servers.
- Discipline routing rule for Composio: check the cached tool map first, one search per workflow, batch independent calls, use the workbench for bulk results, and never run the plugin and a hosted MCP server together.
