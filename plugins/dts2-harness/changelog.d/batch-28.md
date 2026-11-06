### Added

- Onboarding has an optional hooks step: `scripts/hooks-setup.py` (`list`, `recommend`, `apply`) adds hooks you pick to project, local or user settings. It only merges, never overwrites or removes existing hooks, writes a `.bak-<time>` backup first, and supports `--dry-run`.
- Five hook templates under `templates/hooks/` (not registered by the plugin): `command-guard`, `auto-format`, `test-on-stop`, `notify`, `merge-on-green`. `test-on-stop` reads its command only from the active project's `.claude/hooks/dts2/test-command`, so a user-scoped install never runs one repo's tests in another, and setup never replaces an existing `test-command` file.
- `find-skills` now audits every improvement option (hooks, MCP servers, plugins, commands, subagents, permissions, CI) through the read-only `scripts/improve-scan.py`, then wires in your picks.
- Database hook templates: `db-guard` (denies DROP, TRUNCATE, DELETE without WHERE, `prisma migrate reset`, `supabase db reset` and similar) and `migration-check` (non-blocking reminder to review migrations when schema files change). `hooks-setup.py recommend` offers them when it detects a database.
