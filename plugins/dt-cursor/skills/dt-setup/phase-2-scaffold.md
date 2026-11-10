> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# setup - Part 2, scaffold

## Part 2 — Scaffold

Gate: `.harness/end-state.md` has `status: approved`, and `dt_gate.py scaffold` accepts the matching approval digest.

### Single
1. Confirm the repo root and that `.git` exists (warn if not). With `--scaffold-only`, dispatch `dt:scout` now for its `Harnesses:` and `Marketing surface:` lines; every harness it finds is treated as `coexist`.
   A scout report whose first line is `PARTIAL: hit turn cap at <step>` is incomplete: re-dispatch the scout with a narrower scope or a fresh agent before using its output.
2. If `.harness/config.yaml` exists, ask: back up `.harness/` to `.harness.bak-<timestamp>/` and rewrite, merge missing keys only, or abort. (`end-state.md` is never overwritten here.)
3. Detect the stack from root files (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json`, workspace markers such as `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `go.work`).
4. For each harness the user chose to retire: move it to `.harness.bak-<stamp>/<folder>`. Leave `coexist` folders untouched.
5. Write:
   - `.harness/config.yaml` — `project`, `commands` (`test`, `typecheck`, `lint`, `build`, `quick`) taken from real scripts only, `paths` (src, tests, docs, config, generated), `do_not_touch` (`.env`, `.env.*`, `secrets/**`, `**/credentials*`), and a `roster:` block from the Agents round (default `- name: claude`; with `--scaffold-only`, run `roster.py detect` and use the default unless other agents are installed, then ask once). For a monorepo add `packages:` with each package path and its own commands.
   - `.harness/review-checklist.md` — correctness, types, tests, security, conventions, scope, tuned to the stack.
   - `.harness/lessons.md` — header only: `# Lessons` and one line explaining the format `- [L-001] <rule> (source: <run or PR>)`.
   - `.harness/discipline.md` — copy `$PLUGIN/templates/discipline.md`.
   - `.harness/keep.yaml` — copy `$PLUGIN/templates/keep.yaml` if absent; fill `agents:` from the Agents round and append every skill the user said yes to in the Skills round under `skills:` with its `source` (`the publisher's installer for <ref>` exactly as installed, `plugin`, or `synced`) and `serves`. Any plugin the user names as must-keep goes under `plugins:`. Append only; never remove entries. It is committed with the harness and never gitignored.
   - `.harness/state.md` — copy `$PLUGIN/templates/state.md` if absent. Append each harness decision from Round 2b as `- <date> <folder>: <decision>`.
   - `.claude/dts2-harness.local.md` — copy `$PLUGIN/templates/dts2-harness.local.md`.
   - `.agents/product-marketing-context.md` — a stub with headings (product, audience, positioning, pricing, voice), **only** if the repo has a marketing surface (scout's `Marketing surface: yes` for brownfield, the user's stated surface for greenfield) and the file does not exist. This is marketingskills' shared context file and the one file the harness may write under `.agents/`.
6. Run `python3 "$PLUGIN/scripts/dt_gate.py" bridge roster.py resolve --config .harness/config.yaml`. If it errors, show the error and fix the roster with the user.
7. If the Impeccable skill is installed and the repo has a marketing surface (as in step 5) or a UI (a frontend framework, HTML templates, or app screens in the stack; for greenfield, the user's stated surface), run `/impeccable init`.
8. Run `python3 "$PLUGIN/scripts/dt_gate.py" bridge ensure-ignored.py <repo>` to add the harness's ignore entries to `.gitignore`.
8b. Give every detected agent its own project memory file, seeded from one shared source: run `python3 "$PLUGIN/scripts/dt_gate.py" bridge agent-memory.py --write <repo> --agents <installed agents from roster.py detect, comma-separated>`. Do not write `CLAUDE.md` or `AGENTS.md`. The Claude script writes each distinct `rulesFile` when absent; when the file exists it appends only a managed block between `<!-- dts2:start -->` and `<!-- dts2:end -->`, once, and never touches the rest. A second run changes nothing. It runs before step 9, so the managed block already carries the pointer line and step 9 adds nothing twice.
8c. Production scaffold, for the app that the end state describes. Read `appType` from the end state's Production readiness section (run `app-type-detect.py` again when the section is absent) and run `python3 "$PLUGIN/scripts/dt_gate.py" bridge prod-scaffold.py <repo> --app-type <type>`. It writes `.github/workflows/ci.yml` (triggers `pull_request` and `merge_group`; one step per command in `config.yaml`, plus `.harness/checks.sh` when present), and the files that apply to the type: `RUNBOOK.md`, and under `ops/` the monitoring, backups and migrations, credential handoff, rollback and watch, and release notes. It never overwrites a file; report the `skipped` list and the `dropped` list (commands left out of `ci.yml` because they contain `${{` or a newline, are a quoted value that cannot be parsed, or use a YAML form the scaffold does not read; the `ci` check passes without them). Then:
   - File a Decisions action item for each `dropped` command (key and reason), so the user adds that check to CI by hand.
   - Add a Decisions action item for each placeholder the user must fill (provider rollback command, error tracker, uptime URL, alert recipient, backup location), and one to make the `ci` check required on the default branch and in the merge queue (a repo admin step; the harness never changes branch protection).
   - Credentials: follow `ops/credential-handoff.md`. The harness never asks for or stores a production credential; backups and the post-deploy watch use a scoped, short-lived one that a person issues per task.
   - Mark a readiness row `done` in the end state only when its evidence exists and is no longer a placeholder.
   - `ci.yml` is written from the commands at scaffold time; after `config.yaml` commands change, ask before regenerating, and do not overwrite a hand-edited file.
8d. Dependency updates (optional offer, target app only). Skip this step silently when the repo has no package manifest from step 3 (`package.json`, `pyproject.toml`, `requirements*.txt`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json`), when `.github/dependabot.yml`, `.github/dependabot.yaml` or a Renovate config (`renovate.json`, `.renovaterc`, `.github/renovate.json`) already exists, and in batch or `--scaffold-only` runs (list it as an open item instead). Otherwise ask once, default yes: `Add automated dependency update PRs? Dependabot (GitHub-native, default) or Renovate (needs the Renovate app installed) or no?`. On Dependabot, copy `$PLUGIN/templates/dependabot.yml` to `.github/dependabot.yml`, write one `updates` entry per manifest found (its ecosystem and directory, never a guess), and keep the `github-actions` entry only when `.github/workflows/` exists. On Renovate, copy `$PLUGIN/templates/renovate.json` to `renovate.json` and add a Decisions action item to install the Renovate app on the repo. Never overwrite a file, never touch branch protection, and tell the user to review the file before committing.
9. Do not create or edit `AGENTS.md` or `CLAUDE.md`. Leave their bytes unchanged. The Claude edition appended a pointer and this package does not: `Harness state for any agent: .harness/handoff/latest.md (resume with /dt-run resume).` A file that already has the same line ending `(resume with /dts2-harness:run resume).` (pre-4.0 name) counts as there: do not add a second pointer. Change nothing else in the file.
9b. Offer three optional project-settings additions, each as its own yes/no, and write nothing without a yes. All go in the project's `.claude/settings.json` (merge, never overwrite). (a) Belt and braces for the merge guard hook: `permissions.deny` rules `Bash(python3 "$PLUGIN/scripts/dt_gate.py" blocked --action merge *)`, `Bash(git push --force *)` and `Bash(git push -f *)`; say that the first one also stops the head's own approved merges, so the user would merge by hand or drop it before a run. (b) When lanes or autopilot are on: `"subagentPromptCacheTtl": "1h"`, which keeps the prompt cache warm across long subagent turns. (c) Option `autonomy: unattended`, only when the user wants lanes or autopilot to run for hours without permission prompts: run `python3 "$PLUGIN/scripts/dt_gate.py" bridge unattended.py diff` and show the diff first (it adds `permissions.defaultMode: dontAsk`, an allowlist for normal harness work, deny rules that mirror `templates/policy.json`, `disableBypassPermissionsMode: disable` and the sandbox). On a yes run `unattended.py apply` (append-only; an existing value is kept and reported, and the old file is saved as `settings.json.bak-<stamp>`) and then set `autonomy: unattended` in the frontmatter of `.claude/dts2-harness.local.md`. From then on a denied tool call parks the lane with a need-human mailbox item instead of stalling. Say that pushes to the default branch and `python3 "$PLUGIN/scripts/dt_gate.py" blocked --action merge` still need the person's approval.
10. Show the detected commands once and let the user correct them. Tell the user `config.yaml`, `review-checklist.md`, `lessons.md`, `discipline.md`, `state.md` and `end-state.md` are meant to be committed.

### Batch (parallel, scaffold-only)
1. Resolve the repo list. For a folder, list its immediate children that contain `.git`.
2. Run `python3 "$PLUGIN/scripts/dt_gate.py" bridge repo-size.py --json <repo...>` to show size and tier per repo.
3. Dispatch one general-purpose subagent per repo in a single message (cap at 8 per wave; run more waves if needed). Each gets the Single steps above with `--scaffold-only` and its repo path, and writes only inside its own repo. Subagents never ask the user anything: an existing `.harness/config.yaml` means merge missing keys only, the roster is the default `- name: claude`, `.harness/keep.yaml` is copied from the template when absent and never rewritten when present, and each such choice (backup, roster when other agents are installed) comes back as an open item.
4. Collect results into one table: repo, stack, commands found, commands missing, open items, warnings.
5. Resolve missing commands and open items with the user in one pass at the end, not per repo.

### Workspace
One interview covers the whole workspace; Round 5 already wrote and got approval for every per-repo end state and the root end state.
1. Scaffold each repo as in Batch.
1b. Write the workspace keep list next to the manifest: `<workspace root>/.harness/keep.yaml` from `$PLUGIN/templates/keep.yaml`, filled with the Agents round roster, every skill the user said yes to (with its exact install source), and any plugin named as must-keep. Member repos keep their own `.harness/keep.yaml` from the Batch step; a re-run reads the root one first, then each member's, and never re-asks about anything listed in either.
2. Write the manifest in the folder chosen in Round 5, using each repo's `role` from the Repos round and the `depends_on`, contracts and release order from Round 3 (never guessed):
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
The `run` skill reads this to plan cross-repo tasks: contract owners first, consumers after.
