---
name: dt-find-skills
description: "Rescan the repo, audit every improvement option (skills, database tooling, hooks, MCP servers, plugins, commands, subagents, permissions, CI, docs), ask one to three questions, recommend a ranked set, and wire in the picks on a yes. Use when the user says find skills or how can I improve this setup."
disable-model-invocation: true
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-find-skills/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Find skills — rescan, audit, recommend, wire in

Runnable at any point in a project, not only during the setup deep interview. It never changes anything without a yes.

## 1. Rescan
Characterize the repo with the existing read-only scripts:
- `python3 "$PLUGIN/scripts/dt_gate.py" bridge scope-check.py .` (is there a harness, a workspace, an end state)
- `python3 "$PLUGIN/scripts/dt_gate.py" bridge repo-size.py .` (size and tier)
- `python3 "$PLUGIN/scripts/dt_gate.py" bridge env-detect.py` (tools available on this machine)
- `python3 "$PLUGIN/scripts/dt_gate.py" bridge improve-scan.py --cwd .` (read-only audit: facts, an inventory of hooks, MCP servers, plugins, commands, agents and permissions, and recommendations)

The facts come from improve-scan.py: `is_brownfield`, `is_large`, `has_tests`, `has_frontend`, `has_pr` (a GitHub remote or `.github/`), `has_ci`, `has_marketing` (a landing or pricing page), `has_agent_docs` (`CLAUDE.md`, `AGENTS.md`), and the database facts `has_database`, `has_prisma`, `has_supabase`, `has_drizzle`, `has_postgres`, `has_sqlite`. Leave a fact unset when unknown.

## 2. Ask
Ask one to three clarifying questions with AskUserQuestion about what the user wants next (for example: ship a feature, fix bugs, polish the UI, launch). Skip a question the scan already answers.

## 3. Recommend
Run `python3 "$PLUGIN/scripts/dt_gate.py" bridge skill-suggest.py --facts '<the facts from improve-scan as JSON>'`. It returns a ranked list of slugs from the mattpocock companion set (grill-me, improve-codebase-architecture, writing-for-agents, pr, ask-matt, research, diagnosing-bugs), resolve-merge-conflicts from warpdotdev/common-skills, plus design, test and marketing skills. Add any already-installed skills that fit the user's answers.

Merge those skills with the improve-scan recommendations. Database tooling is a featured category: show its items near the top, right after priority 1. Show at most twelve, grouped by category (skills, database, hooks, mcp, plugins, commands, subagents, permissions, ci, docs), each with its priority (1 high, 2 medium, 3 low), a one-line reason, and whether it is already installed or present. Then ask once, with AskUserQuestion multi-select, which to apply.

Composio: if `~/.dts2/composio-tools.json` exists (the Composio tool map), `improve-scan.py` already leaves out MCP recommendations that a connected Composio toolkit covers and lists them under `info` as "covered by Composio (<toolkit>)". Prefer Composio toolkits over installing duplicate MCP servers or plugins, and point the user to `/dt-composio` to build or refresh the map.

## 4. Wire in
On the user's yes, handle only the picked items, per category:
- **skills**: for each chosen skill:
  1. Install it if missing, with `the publisher's installer for <source> --skill <name>` (mattpocock skills use `https://github.com/mattpocock/skills`), into the project only; never `-g`. A failed install prints `Skill <name> not installed (a package launcher unavailable or offline); continuing without it.` and becomes a Decisions action item.
  2. Append it to `.harness/keep.yaml` under `skills:` as `- name: <name>` / `source: <exact install command>` / `serves: harness`, so a setup re-run keeps it. Append only; never remove entries.
  3. Wire it into the run workflow: companion skills follow the table under Companion skills in `.harness/discipline.md`; for a skill outside that table add a row naming when `run` should invoke it, and add it to the `## Skills` table in `.harness/end-state.md` with its phase.
- **database**: database tooling (db guard hooks, database MCP servers, deny rules for destructive commands, a migration check in CI, database skills). Never run migrations, resets, or destructive SQL. MCP servers are read-only by default, with credentials from env vars. Hooks go in through `hooks-setup.py apply --ids db-guard,migration-check --dry-run` first, then apply after the user confirms. Deny rules and CI follow the permissions and ci rules below.
- **hooks**: run `python3 "$PLUGIN/scripts/dt_gate.py" bridge hooks-setup.py apply --ids <picked ids> --dry-run`, show the result, then run the same command without `--dry-run`. It never overwrites existing hooks.
- **mcp**: run `claude mcp add --scope project ...` only for the picked servers. Tokens go in environment variables the user sets; never type them into args or files.
- **permissions**: show the exact lines first, back up `.claude/settings.json`, then append to `permissions.allow` or `permissions.deny`. Never remove entries. Remove a broad allow entry only when the user picks that item.
- **commands and subagents**: write one short new file under `.claude/commands` or `.claude/agents`. Never overwrite an existing file.
- **ci, pr template, dependabot**: copy the plugin template onto a new branch and hand off to `/dt-ship`. Never commit to main.
- **docs**: run `/init`.

## 5. Report
One line per applied item, then a list of what was skipped.

## Guardrails
- Read-only until the user says yes.
- Project scope only by default; user scope only if the user picks it.
- Never remove or overwrite existing entries (keep list, hooks, permissions, commands, agents).
- No secrets in files or commands.
