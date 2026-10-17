---
name: setup
description: Scaffold dts2 harness config (.harness/ and .claude/dts2-harness.local.md) in one repo, in many repos at once in parallel, or as a multi-repo workspace with a shared manifest. Use when the user asks to set up, init, or configure the harness for a repo, several repos, a folder of repos, a monorepo, or a workspace.
---

# Setup — one repo, many repos, or a workspace

## Pick the mode
- One path or the current repo → **single**.
- Several paths, a folder containing several git repos, or "all my repos" → **batch** (each repo gets its own config, done in parallel).
- Repos that ship together (shared API, shared types, one release) → **workspace** (batch plus a workspace manifest).
If batch vs workspace is unclear, ask once. Default to batch.

## Single
1. Confirm the repo root and that `.git` exists (warn if not).
2. If `.harness/` exists, ask: back up to `.harness.bak-<timestamp>/` and rewrite, merge missing keys only, or abort.
3. Detect the stack from root files (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json`, workspace markers such as `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `go.work`).
4. Write:
   - `.harness/config.yaml` — `project`, `commands` (`test`, `typecheck`, `lint`, `build`, `quick`) taken from real scripts only, `paths` (src, tests, docs, config, generated), `do_not_touch` (`.env`, `.env.*`, `secrets/**`, `**/credentials*`). For a monorepo add `packages:` with each package path and its own commands.
   - `.harness/review-checklist.md` — correctness, types, tests, security, conventions, scope, tuned to the stack.
   - `.harness/lessons.md` — header only: `# Lessons` and one line explaining the format `- [L-001] <rule> (source: <run or PR>)`.
   - `.claude/dts2-harness.local.md` — copy `${CLAUDE_PLUGIN_ROOT}/templates/dts2-harness.local.md`.
5. Append idempotently to `.gitignore`: `.harness/runs/`, `.harness/lessons-inbox.md`, `.harness.bak-*/`, `.claude/*.local.md`. Commit `config.yaml`, `review-checklist.md`, and `lessons.md`.
6. Show detected commands once and let the user correct them.

## Batch (parallel)
1. Resolve the repo list. For a folder, list its immediate children that contain `.git`.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo-size.py" --json <repo...>` to show size and tier per repo.
3. Dispatch one general-purpose subagent per repo in a single message (cap at 8 per wave; run more waves if needed). Each gets the Single steps above and its repo path. Each writes only inside its own repo.
4. Collect results into one table: repo, stack, commands found, commands missing, warnings.
5. Ask the user to fix missing commands in one pass at the end, not per repo.

## Workspace
Do Batch, then write a manifest in the parent folder the user picks:
`.harness-workspace.yaml`
```yaml
workspace: <name>
repos:
  - path: ./api
    role: backend
  - path: ./web
    role: frontend
    depends_on: [api]
contracts:            # shared surfaces a change must keep in sync
  - name: api-types
    owner: api
    consumers: [web]
release_order: [api, web]
```
The `run` skill reads this to plan cross-repo tasks: one lane per repo, contract owners first, consumers after.

## Guardrails
- Never overwrite existing config without the user's choice.
- Never guess commands. Leave them empty and say so.
- Never commit or push.
