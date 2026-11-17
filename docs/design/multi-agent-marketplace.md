# Multi-agent marketplace: Codex, Cursor, Grok

Status: design only, no code. Checked against vendor docs on 2026-11-17.

Evidence tags used below:

| Tag | Meaning |
|---|---|
| **V** | Verified: read on the vendor's own doc page during this check (URL given) |
| **VC** | Vendor claim: stated by the vendor but not tested here |
| **C** | Community report: blog or forum, not the vendor |
| **I** | Inference: my reading, needs a test |

## 1. Short answer

| Target | Difficulty | Effort | Works on day one (before any new code) |
|---|---|---|---|
| Cursor | Easy | 0.5 to 1 day | Already shipped as `plugins/dt-cursor` (27 skills, 27 commands, 1 rule, a gate script). Remaining work is housekeeping: wire it into the new single build command, fix version drift, add an Agent Plugins root manifest. |
| Grok (Grok Build CLI) | Easy to medium | 1 to 2 days | Vendor says it reads Claude Code marketplaces, plugins, skills, MCP, agents, hooks and instruction files with no configuration (**VC**). If true, `.claude-plugin/marketplace.json` already works. Needs a 1-hour test. |
| Codex (CLI, IDE, desktop) | Medium | 2 to 3 days | Codex lists `.claude-plugin/marketplace.json` as a legacy-compatible marketplace (**V**), so `codex plugin marketplace add` may list the plugins. Skills should load. Hooks, subagents and `/dt:` commands do not carry over. |
| Shared build tooling | Medium | 1 to 2 days | Two generators with `--check` and CI steps already exist. This adds one wrapper (`scripts/build-adapters.py`) and one more generator for Codex. |

Total: about 6 to 8 working days for all three plus the wrapper, spread over the phases in section 5. The reason it is not harder: since August 2026 there is a cross-vendor package format (Agent Plugins 1.0) for skills and MCP servers that Codex and Cursor both read, and Grok says it reads Claude's format directly. The reason it is not trivial: hooks, subagents, slash-command naming and the Python scripts have no portable format, so they degrade (section 4).

## 2. Current formats (verified)

### 2.1 Cross-vendor baseline: Agent Plugins 1.0

| Fact | Tag | Source |
|---|---|---|
| Spec 1.0.0 published 2026-08-06. Manifest is `plugin.json` at the plugin root. Required fields: `$schema`, `name`. Optional: `version`, `description`, `author`, `homepage`, `repository`, `license`, `keywords`, `extensions` | **V** | https://agent-plugins-site-c7uy8oud2.labs.vercel.dev/specification |
| Only two portable component types: skills (`skills/<name>/SKILL.md`, one level deep) and MCP servers (`mcp.json` at root). Hooks, commands, agents, rules and LSP are explicitly out of scope | **V** | same spec page |
| Day-one clients: ChatGPT and Codex, Cursor, GitHub Copilot, Kiro, VS Code. Contributors: AWS, Anysphere, GitHub, Microsoft, OpenAI, Vercel | **VC** | https://vercel.com/blog/introducing-agent-plugins |
| Claude Code is not in the client list and keeps its own plugin format | **C** | https://codex.danielvaughan.com/2026/08/28/agent-plugins-1-0-open-standard-codex-cli-v0147-multi-vendor-portable-skills-mcp/ |
| The spec defines no marketplace or distribution rules; each client does its own | **V** | spec page |

### 2.2 OpenAI Codex (CLI, IDE extension, desktop)

| Capability | Fact | Tag | Source |
|---|---|---|---|
| AGENTS.md | Global `~/.codex/AGENTS.md` (or `AGENTS.override.md`), then one file per directory from repo root down. Combined cap `project_doc_max_bytes`, default 32 KiB. Extra names via `project_doc_fallback_filenames` | **V** | https://learn.chatgpt.com/docs/agent-configuration/agents-md |
| Skills | `SKILL.md` with `name` and `description` required. Repo `.agents/skills` (cwd up to repo root), user `~/.agents/skills`, admin `/etc/codex/skills`. Explicit call by `$skill-name` or `/skills`. Optional `agents/openai.yaml` for display data and `policy.allow_implicit_invocation` | **V** | https://learn.chatgpt.com/docs/build-skills.md |
| Whether Claude-only frontmatter keys are ignored | Not stated on the page | **I** (test it) | same |
| Plugins | Portable `plugin.json` at root, or `.codex-plugin/plugin.json` as a fallback overlay. Skills discovered from `skills/`, MCP from `mcp.json`. OpenAI says it "also accepts legacy and Claude-compatible manifests" but does not say which path | **V** | https://developers.openai.com/codex/plugins/build.md |
| Marketplace file | `$REPO/.agents/plugins/marketplace.json`, `~/.agents/plugins/marketplace.json`, and legacy-compatible `$REPO/.claude-plugin/marketplace.json` | **V** | same |
| Add a marketplace | `codex plugin marketplace add owner/repo [--ref R] [--sparse PATH]`, also `list`, `upgrade`, `remove`. Config equivalent: `[marketplaces.<name>]` with `source`, `source_type` (`git` or `local`), `ref`, `sparse_paths` | **V** | plugin build page and https://learn.chatgpt.com/docs/config-file/config-reference |
| Install a plugin | The build page documents install through the ChatGPT desktop Plugins Directory, not a CLI install command. A community article lists `codex plugins install` | **V** (page silent) / **C** | build page; https://codex.danielvaughan.com/2026/08/28/agent-plugins-1-0-open-standard-codex-cli-v0147-multi-vendor-portable-skills-mcp/ |
| Installed location | `~/.codex/plugins/cache/<marketplace>/<plugin>/<version>/`. Enable per plugin with `[plugins."name@marketplace"]` in config.toml | **V** | build page |
| MCP servers | `~/.codex/config.toml` tables `mcp_servers.<id>`: stdio (`command`, `args`, `env`) or HTTP (`url`, `bearer_token_env_var`, `auth`). In plugins: root `mcp.json` with `mcpServers` | **V** | config reference; build page |
| Hooks | `features.hooks`. Inline in config.toml or `hooks/hooks.json` in a plugin. Events: SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, PermissionRequest, PreCompact, PostCompact, SubagentStart, SubagentStop, Stop and more. Only command and MCP handlers run. In plugins, hooks work only for plugins installed manually in the desktop app and are not eligible for the public directory | **V** | config reference; build page |
| Hook env vars | Codex sets `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` "for compatibility with existing plugin hooks" | **V** | build page |
| Subagents | One TOML file per agent in `.codex/agents/` or `~/.codex/agents/`. Required: `name`, `description`, `developer_instructions`. Optional: `model`, `model_reasoning_effort`. Whether a plugin can bundle agents: not stated | **V** / not stated | https://learn.chatgpt.com/docs/agent-configuration/subagents.md |
| Custom prompts (`/name` commands) | Replaced by skills in v0.117.0 | **C** | https://codex.danielvaughan.com/2026/04/10/migrating-custom-prompts-to-skills/ |

### 2.3 Cursor (IDE, CLI, Agent Window)

| Capability | Fact | Tag | Source |
|---|---|---|---|
| Plugin formats | Two. "Agent Plugin" (open standard, root `plugin.json`: skills + MCP). "Cursor Plugin" (`.cursor-plugin/plugin.json`: adds rules, agents, commands, hooks, variables). Cursor detects which from the manifest | **V** | https://cursor.com/docs/plugins.md |
| Cursor plugin manifest | Required `name`. Optional `description`, `version`, `author`, `homepage`, `repository`, `license`, `keywords`, `logo`, `rules`, `agents`, `skills`, `commands`, `hooks`, `mcpServers`, `variables` | **V** | https://cursor.com/docs/reference/plugins |
| Marketplace | `.cursor-plugin/marketplace.json` at repo root: `name`, `owner`, `plugins[]` with `name` and `source` (path in repo). Manifest max 10 MB | **V** | reference page |
| Public listing | Public Git repo, submit at cursor.com/marketplace/publish, Cursor team reviews | **V** | reference page |
| Install | Customize panel, pick project or user scope. Local copy under `~/.cursor/plugins/local/<name>` (the existing README documents this) | **V** / repo doc | https://cursor.com/docs/plugins.md; `plugins/dt-cursor/README.md` |
| Team marketplaces | Teams and Enterprise only. Admin sets each plugin Default Off, Default On or Required in Dashboard, Plugins and MCPs. Teams plan: one imported team marketplace | **V** | https://cursor.com/docs/plugins.md |
| Rules | `.cursor/rules/*.mdc` (and `.md`) with `description`, `alwaysApply`, `globs`. Also AGENTS.md | **V** (plugin rules format) | reference page; https://cursor.com/docs/customize-cursor.md |
| Skills | `.agents/skills/`, `.cursor/skills/`, user equivalents, and also `.claude/skills/` and `.codex/skills/`. Frontmatter `name` (must match folder), `description`, `paths`, `disable-model-invocation`, `metadata`. With `disable-model-invocation: true` it acts as a `/skill-name` command | **V** | https://cursor.com/docs/skills |
| Subagents | Markdown with frontmatter in `.cursor/agents/`, `.claude/agents/` or `.codex/agents/` (and user equivalents). Keys: `name`, `description`, `model` (`inherit` default), `readonly`, `is_background`. `.cursor/` wins on name clash | **V** | https://cursor.com/docs/subagents.md |
| Commands | Markdown files invoked with `/`; Cursor can convert them to skills | **V** | customize page; skills page |
| Hooks | `hooks/hooks.json` in a plugin. camelCase events such as `sessionStart`, `preToolUse`, `stop`, `afterFileEdit`, `beforeShellExecution` | **V** | reference page |
| MCP | `.cursor/mcp.json` or `~/.cursor/mcp.json`, top-level `mcpServers`, stdio and remote, `${env:NAME}` and `${workspaceFolder}` interpolation. In plugins use `${CURSOR_PLUGIN_ROOT}` | **V** | https://cursor.com/docs/mcp; reference page |
| VS Code extensions | Not relevant: Cursor's agent customization is the plugin system above. A `.vsix` would only add editor UI and cannot carry skills or rules | **I** | |

### 2.4 Grok (xAI)

| Capability | Fact | Tag | Source |
|---|---|---|---|
| What exists | Grok Build: a coding agent with a TUI, headless mode and ACP (Agent Client Protocol). Installed with `curl -fsSL https://x.ai/cli/install.sh \| bash`. Config in `~/.grok/config.toml`. `grok inspect` lists discovered config, instructions, skills, plugins, hooks and MCP servers | **V** | https://docs.x.ai/build/overview.md |
| Instruction files | Reads `AGENTS.md`, `Agents.md`, `AGENT.md`, `CLAUDE.md`, `CLAUDE.local.md`, every `.grok/rules/*.md`, plus `.claude/rules/` and `.cursor/rules/`. Nested files apply to their subtree. Nearest directory wins | **V** | https://docs.x.ai/build/features/project-rules.md |
| Skills | `.grok/skills/`, `~/.grok/skills/`, enabled plugins' `skills/`, extra `[skills] paths`. Frontmatter: `name`, `description`, `when-to-use`, `paths`, `allowed-tools`, `argument-hint`, `user-invocable`, `disable-model-invocation`, `metadata`. `model`, `effort`, `license`, `compatibility` accepted but ignored | **V** | https://docs.x.ai/build/features/skills-plugins-marketplaces.md |
| Plugins | Can add skills, agents, hooks, MCP servers and LSP servers. Locations: `.grok/plugins/`, `~/.grok/plugins/`, marketplace installs under `~/.grok/plugins/marketplaces/`, `[plugins] paths`, and `--plugin-dir PATH`. Marketplace sources come from `[[marketplace.sources]]` in `~/.grok/config.toml`. The page names no manifest file and no "marketplace add" command | **V** (page silent on both) | same |
| Claude Code compatibility | "Reads Claude Code marketplaces, plugins, skills, MCPs, agents, hooks and instruction files with no configuration" | **VC** (page does not mention `marketplace.json` by name) | same |
| Hooks | Events: SessionStart, SessionEnd, UserPromptSubmit, PreToolUse (only blocking event), PostToolUse, PostToolUseFailure, PermissionDenied, Stop, StopFailure, Notification, SubagentStart, SubagentStop, PreCompact, PostCompact. Files: `~/.grok/hooks/*.json`, `<project>/.grok/hooks/*.json`; also reads `.claude/settings.json` and `.cursor/hooks.json`. Plugin hooks get `GROK_PLUGIN_ROOT` and `GROK_PLUGIN_DATA`. `CLAUDE_PLUGIN_ROOT` is not mentioned | **V** | https://docs.x.ai/build/features/hooks.md |
| MCP | Listed by `grok inspect` and manageable in `/mcps`; plugins can bundle them. Config format not on the pages read | **V** (partial) | overview and plugins pages |
| Subagents | Plugins can add agents; file format not on the pages read. This repo's `profiles/agents/grok.json` already passes `--no-subagents` | **V** (partial) | plugins page; repo profile |
| Official plugin format of its own | None found named. No separate API-level "plugin" product. The xAI API is a model API, not an agent surface | **I** | |
| Community tools | Several third-party guides and `.grok/skills` collections exist. Treat as unofficial | **C** | e.g. https://github.com/DominikTobureto/awesome-grok-build |

Note: this repo's `profiles/agents/grok.json` has `"verified": false`. The Grok facts above are the first doc-level check; nothing here was run against a real Grok install.

## 3. Component mapping

dt components counted from the repo: 29 skills (28 after the Cursor build drops `go`), 8 agents (`lead`, `builder`, `reviewer`, `verifier`, `fixer`, `auditor`, `scout`, `incident-reviewer`), 19 hook shell scripts wired to 12 Claude events, 106 Python scripts, 1 profile set, 0 bundled MCP servers (fleet-ledger is SQL plus a Python client).

| dt component | Codex | Cursor | Grok |
|---|---|---|---|
| Skills (`skills/<n>/SKILL.md`) | Native: `skills/` in a plugin or `.agents/skills/`. Call as `$dt-check-in` | Native: `skills/`. With `disable-model-invocation: true` it is `/dt-check-in` | Native: `skills/` in plugin or `.grok/skills/`. Claude frontmatter keys overlap |
| Slash commands (`/dt:check-in`) | No colon namespace. Skill name becomes the handle (`$dt-check-in`). Degrade to skill | `/dt-check-in` only. Plugin name is not prefixed. Already built | Same skill route. Whether a plugin prefix applies is untested (**I**) |
| Agents (8 subagent `.md`) | Convert to `.codex/agents/<n>.toml` (`developer_instructions` = body). Drop `tools`, `maxTurns`, `color`. Bundling in a plugin not documented, so ship by copy script | Native-ish: `.cursor/agents/` or read from `.claude/agents/`. `model: sonnet` should map to `inherit` | Plugins can carry agents (**V**); format unconfirmed. Likely reads Claude agents (**VC**) |
| Hooks (12 events, 19 scripts) | Native events exist, plugin hooks only in desktop app manual installs. `CLAUDE_PLUGIN_ROOT` is set, so scripts may run as is. CLI users: print the config.toml block, do not auto-install | Different schema and event names. No auto-translation. Degrade to the gate script (already how dt-cursor works) | Event names match Claude's. Reads `.claude/settings.json`. Variable is `GROK_PLUGIN_ROOT`, so a one-line alias in each hook script is needed |
| MCP servers | `mcp.json` in plugin, or `[mcp_servers.x]` in config.toml. dt ships none today | `mcp.json` with `${CURSOR_PLUGIN_ROOT}` | Plugin-bundled, format unconfirmed |
| Python scripts (`scripts/*.py`) | Run through the shell tool when the plugin cache path is known. Pass the path via a rendered skill preamble. Sandbox may block writes outside the workspace | Cursor package forbids them and routes through `dt_gate.py` | Runs through its Bash tool. Path via `GROK_PLUGIN_ROOT` |
| Profiles (`profiles/*.json`, `blueprint.json`) | Plain data files. Ship in the package, read by scripts | Same | Same |
| Rules / always-on guidance | `AGENTS.md` (32 KiB cap, so keep short) | `rules/*.mdc` | `AGENTS.md` or `.grok/rules/*.md` |

Reverse direction, already done: `profiles/agents/codex.json` and `grok.json` let dt call Codex and Grok as worker seats. That is dt using them, not them installing dt. It is a different feature.

## 4. Adapter plan

### 4.1 Principle

One canonical source: `plugins/dts2-runtime/`. Everything else is generated, never edited. This is the pattern the repo already uses twice, so the plan extends it rather than inventing one.

| Existing | Output | Check |
|---|---|---|
| `plugins/dts2-runtime/scripts/directory_edition.py` | `plugins/dts2-harness/` | `--check`, CI step "Directory edition matches the generator" |
| `plugins/dts2-runtime/scripts/cursor_surface.py` (reads the harness edition) | `plugins/dt-cursor/`, `.cursor/`, `.cursor-plugin/` | `--check`, CI step "Cursor surface matches the generator", unit test `test_cursor_surface.py` |

`cursor_surface.py --check` was run on this branch and passes (175 files).

### 4.2 New layout

| Path | What | Generated by |
|---|---|---|
| `scripts/build-adapters.py` (repo root, new folder) | Single entry point: `--target {harness,cursor,codex,grok,all} [--check]`. Thin wrapper that calls the existing generators in the existing order, then the new ones. Exit 1 and a diff summary on drift | hand-written |
| `plugins/dt-codex/` | Codex package: root `plugin.json` (Agent Plugins), `skills/dt-*/`, optional `agents/*.toml`, optional `hooks.snippet.toml`, short `AGENTS.md` | `plugins/dts2-runtime/scripts/codex_surface.py` (new, modelled on `cursor_surface.py`) |
| `.agents/plugins/marketplace.json` | Codex marketplace entry pointing at `plugins/dt-codex` | same generator |
| `plugins/dt-cursor/` | Existing. Add a root `plugin.json` (Agent Plugins form) beside `.cursor-plugin/plugin.json` | `cursor_surface.py` |
| `plugins/dt-grok/` | Only if the Phase 0 test shows Grok cannot use the Claude plugin directly. Otherwise no folder | `grok_surface.py` (conditional) |

Reuse rule: Codex and Cursor both derive from the instruction edition (`plugins/dts2-harness`), because that edition already removes the parts that need hooks and bundled scripts. Grok, if it needs anything, derives from the full runtime, because it can run hooks.

### 4.3 CI

Replace the two generator steps in the `metadata` job of `.github/workflows/test.yml` with one:

```
- name: Adapter outputs match the generators
  run: python3 scripts/build-adapters.py --target all --check
```

It fails the pull request when any generated file is stale or hand-edited. The existing release gate (`release-gate.py`) already forces a `plugin.json` version bump when the runtime changes.

### 4.4 Versioning

| Item | Rule |
|---|---|
| Source of truth | `plugins/dts2-runtime/.claude-plugin/plugin.json` `version` (5.3.0 now) |
| Generated manifests | Every adapter copies that version. A test fails if any differs |
| Existing drift to fix | `plugins/dt-cursor/.cursor-plugin/plugin.json` says 6.0.0 while the runtime says 5.3.0. Either intentional (Cursor package versioned on its own) or a bug. Decide, then make `--check` enforce it |
| Marketplace manifests | `.claude-plugin/marketplace.json` already carries `version`. Generate the Codex marketplace entry from it |

### 4.5 User install and sync per target

Command forms marked **V** in the notes come from vendor docs; the rest is the plan and must be run once to confirm.

| Target | Install | Sync (update) |
|---|---|---|
| Claude Code (today) | `/plugin marketplace add <owner>/dts2-marketplace` then `/plugin install dt@dts2` | `/plugin marketplace update dts2` |
| Codex | `codex plugin marketplace add <owner>/dts2-marketplace` (**V** command form). Then install `dt` through the Plugins Directory, or enable it with `[plugins."dt@dts2"]` in `~/.codex/config.toml`. Fallback with no plugin support: copy `plugins/dt-codex/skills/*` to `~/.agents/skills/` | `codex plugin marketplace upgrade dts2` (**V**). Fallback: `git pull` and re-copy |
| Cursor | Team: import the repo as a team marketplace (Dashboard, Plugins and MCPs). Individual: copy `plugins/dt-cursor` to `~/.cursor/plugins/local/dt` (existing README steps). Public: submit via cursor.com/marketplace/publish (`SUBMISSION.md` exists) | Team marketplace re-syncs from Git. Local copy: re-copy |
| Grok | Try first: add `https://github.com/<owner>/dts2-marketplace` as a `[[marketplace.sources]]` entry in `~/.grok/config.toml`, or `grok --plugin-dir plugins/dts2-runtime` for a local test. Browse in the TUI Marketplace tab or `/plugins` | Marketplace tab refresh. Local: `git pull` |

### 4.6 How hooks and Python scripts degrade

| Situation | Rule |
|---|---|
| Target has hooks and a matching variable (Grok, Codex desktop) | Ship the same hook scripts. Add one fallback line at the top of each so a single script serves both: use `GROK_PLUGIN_ROOT` when `CLAUDE_PLUGIN_ROOT` is unset |
| Target has hooks but a different schema (Cursor) | Do not translate silently. Ship no hooks. Move the enforcement the hook gave into the skill text plus a gate script check, as `dt_gate.py` does now |
| Target has no hooks or they cannot ship in a plugin (Codex CLI) | Generate `hooks.snippet.toml` with the exact `[hooks.*]` blocks and a skill (`dt-hooks`) that explains how to paste it. Nothing is installed without the user doing it |
| Script needs Claude-only features (headless SDK, fleet broadcast, merge) | Same blocker model as `dt_gate.py blocked`: exit with a named `UNSUPPORTED` code, require the explicit approval phrase, then stop. Never imitate the step |
| Script is pure Python and read-only (check-in, context-tax) | Run as is via the shell tool. The skill text states the path with a per-target variable |
| No Python on the machine | Skills that need a script say so in one line and stop; they do not guess |

## 5. Risks, open questions, phased rollout

### 5.1 Risks

| Risk | Why | Mitigation |
|---|---|---|
| Format churn | Agent Plugins is 3 months old; Codex docs moved URLs during this check; Grok docs are dated mid-2026 | Pin the spec version in each generated manifest. Keep generator logic small. Recheck docs each release |
| Skill behavior differs | Same SKILL.md, different loaders, different permission models | A shared smoke test per target: `check-in` skill with no end state must print the fixed sentence |
| Security surface grows | Hooks and scripts run on three more agents. A third-party study cited in a community article reports many public skills have flaws (**C**) | Default to the degraded, no-hook build everywhere. Hooks only on explicit opt-in |
| Skill count and context cost | 29 skills loaded into a Codex session costs tokens; AGENTS.md has a 32 KiB cap | Reuse `context-tax.py` per target. Set `allow_implicit_invocation: false` in `agents/openai.yaml` for command-style skills |
| Namespace loss | `/dt:run` becomes `$dt-run` or `/dt-run` | Document one table of command names per target |
| Maintenance load | Four outputs from one source | The single `--check` job. Generators share one parsing module |
| Public-directory limits | Codex says plugin hooks are not eligible for the public directory (**V**) | Public Codex listing ships the no-hook build |

### 5.2 Open questions (each is a test, not a debate)

1. Does `codex plugin marketplace add` accept this repo as is, and does it load a plugin that has only `.claude-plugin/plugin.json`? (OpenAI names the marketplace path, not the plugin manifest path.)
2. Does Codex ignore Claude-only frontmatter (`allowed-tools`, `argument-hint`) or reject the skill?
3. Does Grok read `.claude-plugin/marketplace.json` from a configured marketplace source, and does it expand `${CLAUDE_PLUGIN_ROOT}` in `hooks.json`? Its docs name `GROK_PLUGIN_ROOT` only.
4. Can a Codex plugin bundle subagent TOML, or must they be copied to `.codex/agents/`?
5. Is the 6.0.0 Cursor version intentional?
6. Do Cursor's Agent Plugin and Cursor Plugin forms coexist in one folder, or must they be separate packages?
7. Is a `dt` MCP server worth building as the one truly portable surface? None exists today.

### 5.3 Phases

| Phase | Scope | Effort | Exit test |
|---|---|---|---|
| 0: spike | Run questions 1 to 3 against the current repo on real installs. No code. Record results in this file | 0.5 day | Written yes or no per question |
| 1: Codex | `codex_surface.py`, `plugins/dt-codex/`, `.agents/plugins/marketplace.json`, hook snippet, agent TOML conversion, tests modelled on `test_cursor_surface.py` | 2 to 3 days | `$dt-check-in` prints the fixed no-end-state sentence in a fresh Codex session |
| 2: wrapper and CI | `scripts/build-adapters.py`, swap the two CI steps for one, version-equality test, resolve the 6.0.0 drift | 1 day | PR with a stale adapter fails CI |
| 3: Grok | Per spike result: either docs only (point to the Claude marketplace) plus the one-line variable fallback in hook scripts, or a `grok_surface.py` build | 1 to 2 days | `grok inspect` shows the dt skills, and `check-in` passes |
| 4: Cursor polish | Add Agent Plugins root manifest, confirm team-marketplace import, submit listing | 0.5 to 1 day | Team marketplace install on a test org |
| 5: optional | Portable `dt` MCP server so all targets share one tool surface | not sized | Separate design |

Phase 1 is Codex because it has the most documented marketplace and hook story of the three. Grok costs almost nothing if the spike shows the Claude plugin works unchanged, since then it needs only docs.

## 6. Small and separable now?

| Piece | Small enough to do now? | Why |
|---|---|---|
| Phase 0 spike (three install tests, no code) | Yes, about half a day | Pure checking. It decides whether Grok needs any code and whether Codex can use the Claude marketplace unchanged. Best first move |
| `scripts/build-adapters.py` wrapper over the two existing generators plus one CI step | Yes, about half a day | Touches no generated output. Independent of Codex and Grok |
| Fix or document the 6.0.0 versus 5.3.0 version mismatch | Yes, under an hour | One decision plus a test |
| Variable fallback line in the 19 hook scripts | Yes, small, but wait for spike question 3 | Only needed if Grok needs it |
| Codex generator, Grok generator, hook snippet, agent TOML conversion | No | Needs the spike results first and about 3 to 5 days |

Nothing in this document was implemented. This commit adds the design file only.

## 7. Sources

All checked 2026-11-17.

- Agent Plugins spec: https://agent-plugins-site-c7uy8oud2.labs.vercel.dev/specification and https://vercel.com/blog/introducing-agent-plugins
- Codex plugins: https://developers.openai.com/codex/plugins/build.md
- Codex config reference: https://learn.chatgpt.com/docs/config-file/config-reference (redirected from developers.openai.com)
- Codex AGENTS.md: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- Codex skills: https://learn.chatgpt.com/docs/build-skills.md
- Codex subagents: https://learn.chatgpt.com/docs/agent-configuration/subagents.md
- Cursor plugins: https://cursor.com/docs/plugins.md and https://cursor.com/docs/reference/plugins
- Cursor skills, subagents, MCP, customize: https://cursor.com/docs/skills , https://cursor.com/docs/subagents.md , https://cursor.com/docs/mcp , https://cursor.com/docs/customize-cursor.md
- Grok Build: https://docs.x.ai/build/overview.md , https://docs.x.ai/build/features/skills-plugins-marketplaces.md , https://docs.x.ai/build/features/hooks.md , https://docs.x.ai/build/features/project-rules.md
- Community (unofficial): https://codex.danielvaughan.com/2026/08/28/agent-plugins-1-0-open-standard-codex-cli-v0147-multi-vendor-portable-skills-mcp/ , https://codex.danielvaughan.com/2026/04/10/migrating-custom-prompts-to-skills/
