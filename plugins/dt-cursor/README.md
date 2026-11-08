# dt for Cursor

DT: Init to Ship Auto Agent Orchestrator. A Dobeu Tech Solutions LLC product. MIT. Copyright Dobeu Tech Solutions LLC. https://dobeu.net

This folder is the Cursor instruction package. It is separate from the Claude Code plugin. Claude Code still installs the full harness from `plugins/dts2-runtime` (`/plugin install dt@dts2`) or the instruction edition at `plugins/dts2-harness`.

## What Cursor loads

| Piece | Path | Cursor name |
|---|---|---|
| Skill | `skills/dt/SKILL.md` | `/dt` (explicit invoke; `disable-model-invocation: true`) |
| Commands | `commands/dt-*.md` (27) | `/dt-<skill>`, from the filename stem |
| Rule | `rules/instruction-edition.mdc` | Applied when a `/dt` command is in use (`alwaysApply: false`) |
| Logo | `assets/icon.png` | The existing listing icon |

There is no `hooks/` directory and no `mcp.json`. The manifest sets `skills`, `commands`, and `rules`, so Cursor does not also scan a Claude `skills/` or `agents/` tree.

## Namespace

Claude Code builds `/dt:check-in` from the plugin name `dt` plus the skill `check-in`. Cursor's current plugin reference takes the command slug from the filename and does not add the plugin name. Skill names are lowercase letters, numbers, and hyphens, and must match the folder. A colon does not fit either rule.

`/dt:check-in` in Cursor is a different string from `/dt-check-in`. A manifest does not make the colon form appear.

## Read-only commands

`/dt-check-in`, `/dt-onboard`, and `/dt-action-items` read the workspace and write nothing. `/dt-run` is not a smoke test: the Claude `run` skill's pre-check can install or update files before a build. There is no `/dt-respond` command. `/dt-fleet` does not list sessions, and the Claude description it quotes is one computer, not every computer. With no `.harness/end-state.md`, `/dt-check-in` stops with:

`No end state yet; /dt:setup interviews to one.`

The other 24 commands are in the slash list and stop before scripts, package installs, credential reads, merges, force-pushes, deploys, and branch deletes. `/dt-gtm` records the marketing-skill renames from `skills-bundled/README.md` (checked 2026-11-07) and does not install that pack. `/dt-pr-sweep` does not merge. `/dt-sdk` is not in the Claude instruction edition; the command does not start a headless run.

## Install

A file on disk is not a loaded command. Confirm the slash list in the session you are testing, then run `/dt-check-in` and expect the sentence above when the repo has no end state. Do not use `/dt-run`, `/dt-ship`, `/dt-pr-sweep`, `/dt-fullauto`, or `/dt-gtm` as the smoke test.

This repo already contains `.cursor/skills/dt/SKILL.md` and `.cursor/commands/dt-*.md`. A new Cursor session opened on this repo can discover those project files. A session that is already running keeps the catalog it started with. Other repositories, automations, and self-hosted workers do not receive them. Self-hosted workers show plugin skills when that plugin is installed on the worker, or project skills from the repo that worker opened.

Before this package is on the branch a marketplace tracks, importing `https://github.com/Dobeu-tech-eco/dts2-marketplace` does not install these commands. Until then, install from a copy of the validated commit, in a new directory, so existing checkouts stay untouched:

```
git clone --branch cursorchima_cursor-dt-plugin-cb0d --single-branch \
  https://github.com/Dobeu-tech-eco/dts2-marketplace.git /tmp/dts2-cursor-plugin
mkdir -p ~/.cursor/plugins/local
if [ -e ~/.cursor/plugins/local/dt ]; then
  mv ~/.cursor/plugins/local/dt ~/.cursor/plugins/local/dt.previous
fi
cp -R /tmp/dts2-cursor-plugin/plugins/dt-cursor ~/.cursor/plugins/local/dt
```

After this package is on the marketplace's tracked branch, clone that branch instead. If `dt.previous` already exists, pick another name. The move keeps the previous folder.

Use a real copy. Cursor skips a symlink in `~/.cursor/plugins/local` when the target sits outside that folder. Reload the window. Open Customize and confirm the skill `dt` and the command `dt-check-in`. On Enterprise, local imports stay off until an admin turns on Allow Local Plugin Imports. If a marketplace plugin named `dt` is already installed, that install wins over the local copy.

Do not install the cached `dts2-harness` 2.1.0 tree at ref `c4f5e8d`. That cache has a Claude manifest and no Cursor commands, and the machines checked so far do not list it in `.cloud-plugin-manifest.json`.

Leave `~/.claude/plugins` alone. Do not reset, clean, or check out another branch in an existing clone.

## License

MIT. See [LICENSE](../../LICENSE). Fork it, change it, and keep the copyright notice for Dobeu Tech Solutions LLC.

Company pages: https://dobeu.net/privacy and https://dobeu.net/terms. Issues: https://github.com/Dobeu-tech-eco/dts2-marketplace/issues
