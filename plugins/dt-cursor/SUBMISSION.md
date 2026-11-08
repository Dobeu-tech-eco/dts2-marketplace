# Cursor submission package

Prepared for a parent to submit. This file is not a submission. Nobody has been contacted, and nothing has been sent to Cursor or Anthropic from this change. Listing in the Cursor Marketplace is not claimed.

## Where the parent submits

Official destination, from the current Cursor docs (fetched 2026-11-08):

- Publish page: https://cursor.com/marketplace/publish
- Requirements: https://cursor.com/docs/reference/plugins (Submitting a plugin, and the checklist on that page)
- Product overview: https://cursor.com/docs/plugins
- Skills and where they load: https://cursor.com/docs/skills

The publish docs say to host a public Git repository and submit the repository link. Cursor reviews every plugin manually. A multi-plugin repo needs `.cursor-plugin/marketplace.json` at the repo root. This repo has that file, with one plugin, `dt`, source `plugins/dt-cursor`.

Submit after this package is on the branch the form will index. Importing or publishing the default branch before that merge will not contain `plugins/dt-cursor`. The docs describe the tracked branch as the branch the marketplace follows. They do not promise that a pull-request branch can be selected.

Team marketplace import (Dashboard, Plugins and MCPs, Import from Repo) is a separate, private distribution path. It is not the official marketplace, and it is not done here.

## Anthropic source, copied

Recovered 2026-11-08 from the signed-in page https://claude.ai/directory/manage/plugins/1d35c2d0-7617-4fcb-a4ba-c80da0f64bdf?tab=feedback. No portal action was taken. The page is a manage URL. A Feedback tab does not, by itself, prove a status. The page text does.

Visible status: **Needs changes**. Directory policy refused this version. Progress shows Submitted done, Needs changes current, In review not yet, Live not yet. Overview: nothing published yet. Review decision shown: an automatic check. No human acceptance and no live listing.

Exact listing fields on that page:

| Field | Value |
|---|---|
| Display name | DT: Init to Ship Auto Agent Orchestrator |
| Plugin name | dt |
| Description | A Claude Code harness that turns one task into a planned, built, reviewed and verified pull request, with human checkpoints, parallel lanes and a paper trail. |
| Author | Dobeu Tech Solutions LLC |
| Homepage | dobeu.net |
| Documentation | (empty) |
| Support | github.com/Dobeu-tech-eco/dts2-marketplace/issues |
| Repository | github.com/Dobeu-tech-eco/dts2-marketplace |
| Privacy policy | dobeu.net/privacy |
| Terms of service | dobeu.net/terms |
| License | MIT |
| Keywords | harness, multi-agent, pipeline, monorepo, agent-sdk, wsl |
| Plugin directory shown | plugins/dts2-harness |
| Branch shown | main |
| Version label | v5.1.1 |
| Commit shown | fb7e4d5b88ee5e93741f677fa3dce6af2edfa5c6 |

Automatic blocks, quoted in the recovery: command hooks only from Verified organizations; files outside Markdown, text, JSON, YAML, and PNG/JPEG/GIF/WebP/ICO, plus shebangs and package-manager config, only from Verified organizations; frontmatter keys outside that directory's allowlist only from Verified organizations. Those are Anthropic directory rules. They are not Cursor's rules. This package does not reuse them as Cursor policy.

## What the repo at that commit actually contains

Checked with `git show` and `git ls-tree` on `fb7e4d5b88ee5e93741f677fa3dce6af2edfa5c6` (current `main` when this package was built). The portal counts were not used as the file list.

| Tree | Version in plugin.json | Skills | Agents | Command hooks |
|---|---|---|---|---|
| `plugins/dts2-harness` at fb7e4d5 | 6.0.0 | 26 (`sdk` absent) | 8 | 0 |
| `plugins/dts2-runtime` at fb7e4d5 | 5.1.1 | 27 | 8 | 33 |
| `plugins/dts2-harness` at parent 690d8df (PR 100) | 5.1.1 | 27 | 8 | 33 |

Parent 690d8df is the last commit before the directory split. Runtime did not exist yet. Its harness counts match the portal overview (27 skills, 8 agents, 33 command hooks). The submitted description string matches `plugins/dts2-runtime/.claude-plugin/plugin.json` at fb7e4d5 and the parent harness manifest. It does not match the 6.0.0 harness description.

`.claude-plugin/marketplace.json` at fb7e4d5 installs `./plugins/dts2-runtime` as `dt` version 5.1.1. The harness directory is the instruction edition and is not the GitHub marketplace entry.

The portal can show commit fb7e4d5, version v5.1.1, and 33 hooks on one screen while `plugins/dts2-harness` at that commit has version 6.0.0 and zero hooks. Treat the page's version label and the git tree as two records.

## Cursor manifest (what the indexer will read)

`plugins/dt-cursor/.cursor-plugin/plugin.json`:

| Field | Value | Why it differs from the Anthropic page, if it does |
|---|---|---|
| name | dt | Same plugin name. |
| description | DT: Init to Ship Auto Agent Orchestrator. Turns one task into a planned, built, reviewed and verified pull request, with human checkpoints, parallel lanes and a paper trail. In Cursor this is an instruction package: the /dt skill and /dt-\<command\> prompts. It does not include hooks or scripts. | The Anthropic sentence calls it a Claude Code harness. This package does not run Claude Code. The title and the rest of the sentence are the submitted copy. |
| version | 6.0.0 | Tracks the instruction edition in this repo. The portal's v5.1.1 label is the runtime / pre-split tree. |
| author | Dobeu Tech Solutions LLC | Cursor's documented author fields are `name` and optional `email`. No email is invented. Homepage is a separate field. |
| homepage | https://dobeu.net | Same site. |
| repository | https://github.com/Dobeu-tech-eco/dts2-marketplace | Same repo. |
| license | MIT | Same. |
| keywords | harness, multi-agent, pipeline, monorepo | `agent-sdk` and `wsl` stay in the Anthropic keyword list above. This package does not ship a Claude Agent SDK or a WSL setup, so they are not manifest keywords. Paste the full Anthropic list into the form only if the form asks for the original keywords. |
| logo | assets/icon.png | Copy of `plugins/dts2-harness/.claude-plugin/icon.png`. Cursor resolves a relative logo against the repo. |

Cursor's documented manifest does not include support, privacy, terms, or documentation fields. If the publish form has those boxes, paste:

- Support: https://github.com/Dobeu-tech-eco/dts2-marketplace/issues
- Privacy: https://dobeu.net/privacy
- Terms: https://dobeu.net/terms
- Documentation: leave empty, matching the Anthropic page, or point at `plugins/dt-cursor/README.md`

Marketplace registration: `.cursor-plugin/marketplace.json`, name `dts2`, one plugin, source `plugins/dt-cursor`.

## What was left out, and the Cursor reason

Cursor's own reference allows rules, skills, agents, commands, MCP, and hooks. Anthropic's refusal of command hooks is not why this package omits hooks.

The 33 command hooks in `plugins/dts2-runtime/hooks/hooks.json` each run `bash` with a Claude plugin-root variable and a script. Cursor would be able to store a hook, and those hooks would also run on their own. They are omitted because they call scripts this instruction package does not contain and because a smoke test of them would change a session. The same is true of the runtime `scripts/` tree.

The eight Claude agents stay in `plugins/dts2-harness/agents` and `plugins/dts2-runtime/agents`. They are not registered as Cursor subagents. Their frontmatter includes Claude tool lists and model names, and default discovery would publish short names such as `lead` from files that tell the agent to run those scripts.

`plugins/dts2-harness/skills/` is not the Cursor skill path. Default discovery would name the skills `run`, `sdk`, and `autopilot`. Cursor already uses `/sdk` and `/autopilot`, and the CLI uses `/run` as a shell alias. The manifest points at `skills/`, which contains only `dt`.

## Checklist against the Cursor reference

- `.cursor-plugin/plugin.json` exists and parses. `name` is `dt`.
- Paths in the manifest are relative and stay inside the plugin. No `..`.
- The skill has `name` and `description`, and `name` matches the folder `dt`.
- Each command file is `.md`, with `name` and `description`. The name matches the filename stem `dt-<skill>`.
- The rule has `description` and `alwaysApply`.
- README covers purpose, install, component coverage, and the MIT license.
- Logo file exists at the declared relative path.
- No secret values are in the package.

## Local rollout the parent can run later

Checked runtimes, not every Cursor install on the account:

- Mac Cursor 3.29.14, cursor-agent 2026.11.05-86047df: injected skills had no dt. Claude user install was `dt@dts2` 5.1.1 from `plugins/dts2-runtime` (git 1c872e4). Stale Cursor cache `dts2-harness` 2.1.0 ref `c4f5e8d` was not in `.cloud-plugin-manifest.json`. No `~/.cursor/skills` and no `plugins/local` install. The local clone is `evolve/gemini-grok-roles` at 5621f51 (harness 3.3.1 only). Leave that checkout as it is.
- WSL Cursor 3.29.14, cursor-agent 2026.10.19-6bbf2c4: same gap for the 2.1.0 cache (Claude manifest only, absent from a 46-entry manifest and from injected skills). No `~/.cursor/skills` or commands. Active Claude there is `harness@harness` 1.0.1 from plugin-claudeharness, not dts2. chimacomics has no `.harness/` and its dirty `AGENTS.md` and `CLAUDE.md` stay dirty.
- Windows worker `0a83a21149` was not part of those two skill-injection reports. Do not infer a result for it. Its chimacomics checkout was already dirty and ahead/behind; do not reset it.
- This managed-cloud pod's `~/.cursor/plugins/cache/.cloud-plugin-manifest.json` (created 2026-11-08T19:38:03Z) lists 46 user plugins. None is named `dt` or `dts2`. The agent session that built this package did not have `dt` in its injected skill list. That is this pod, not a census of every cloud environment.
- An architecture review at `fb7e4d5` (Eggbot, accepted as design only) found an installed catalog that listed `dt` with 27 skills while skill loading failed. A catalog entry is not a loaded skill. There is no `respond` skill in `plugins/dts2-runtime/skills/` and this package does not add `/dt-respond`.

Pre-existing docs disagree about fix-round caps (discipline says five; delegate uses three Sonnet rounds; autopilot also describes a council cap of two and a CI cap of five). Those files were not edited here.

Safe smoke, after the copy in the README, in a new session: invoke `/dt-check-in` only. Expect the missing-end-state sentence when that workspace has no `.harness/end-state.md`. Confirm the command was selectable. A file existing under `plugins/dts2-harness/skills/` does not count as success.

Do not install ref `c4f5e8d`.
