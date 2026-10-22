---
name: setup
description: Interviews the user to an approved end state (.harness/end-state.md), then scaffolds dts2 harness config (.harness/ and .claude/dts2-harness.local.md) in one repo, many repos in parallel, or a linked multi-repo workspace. Use when the user asks to set up, init, or configure the harness, onboard a repo, run the interview, define or revise the end state, or link repos into a workspace. `--scaffold-only` skips the interview.
---

# Setup — interview to an end state, then scaffold

Setup has two parts. **Part 1** interviews the user until the end state is clear and approved. **Part 2** writes the harness files. Part 2 never starts until the user approves the end state, unless `--scaffold-only` was given.

## Scope and keep list

Before anything else, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" .`.
- `workspace-member` → ask once `This folder is a member of workspace <root>. Run setup at the workspace root instead? (y/n)`. Yes → continue with the workspace root as the project path.
- `workspace-root` with an existing manifest → offer `Re-link the existing workspace (no interview) or revise the end state?`.
- If `.harness/keep.yaml` exists at the effective root, read it and say `Keeping <n> plugins, <n> skills, <n> agents from .harness/keep.yaml`. Skip the install question for every listed skill (never re-ask), pre-include the listed agents in the Agents round (still show them), and never propose disabling a listed plugin. A re-link or pivot re-run never rewrites keep.yaml except to append.

## Mode

- One path or the current repo → **single**: Part 1, then Part 2.
- Several paths, a folder of git repos, or "all my repos" → **batch**: Part 2 only, per repo, in parallel (batch is always scaffold-only; run setup in a repo later to interview it).
- Repos that ship together (shared API, shared types, one release), or any repo tagged `linked` in the Repos round → **workspace**: one interview, then a per-repo end state, a root end state for cross-repo components, and a workspace manifest.
- `--scaffold-only` → skip Part 1 and run Part 2 directly. Leave any existing `.harness/end-state.md` as it is.

If batch vs workspace is unclear, ask once. Default to batch.

If `.harness/end-state.md` already exists, show its status and ask once: revise it, keep it and scaffold (only if its status is `approved`), or start over. For revise and keep-and-scaffold, read `roster` from its metadata and the decisions from its Other harnesses table, and re-run `dts2-harness:scout` for fresh `Harnesses:` and `Marketing surface:` lines. Revise resumes the interview from the file's contents; keep-and-scaffold goes straight to Part 2.

## Part 1 — Interview

Rules for the whole interview:
- Ask **one question per message**. Plain words, no jargon, no internal names like "dimension" or "weakest".
- Until the end state is written, the only writes are the temporary ratings file (outside the repo) and any skill installs the user says yes to.
- Keep a running record as you go: mode (greenfield or brownfield), related repos, harness decisions, roster, components, answers, rounds, clarity.

### Round 1 — Greenfield or brownfield

1. Look at the repo root. **Greenfield** if there is no source code yet (empty, or only README, LICENSE, `.gitignore`, config stubs). Otherwise **brownfield**.
2. Brownfield: dispatch the `dts2-harness:scout` agent on the repo and keep its output. You need its `Harnesses:` line, its `Marketing surface:` line, and the stack and modules it reports. Also read any existing `.harness/` files (config, lessons, state) for context.
3. Tell the user in one line what you found, for example: `Brownfield: TypeScript monorepo, 4 packages, marketing site found.`

### Round 2 — Repos

Always ask this before any question about components. Ask exactly:

> Paste any other repos that matter here, one per line. Say "none" if there aren't any.

For each repo the user pastes, ask in one message: **what is it, and what it serves** in relation to this project. Store the answer as its `role`. Then tag it (propose a tag and let the user correct it):
- `context` — read for conventions and contracts; never edited.
- `linked` — it ships with this repo and joins a multi-repo workspace. Any `linked` repo switches the mode to **workspace**. Ask for its local path (or offer to clone it next to this repo).

Context repos are cloned only when someone needs to read them: `git clone --depth 1 <url> ~/.dts2/context/<owner>-<repo>`. Never clone into the project.

### Round 2 (continued) — Deploy target

Greenfield: skip this step here and ask it right after the Topology round, once you know what is being built.

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/deploy-detect.py" <repo>` (it only reads files and never runs the check command). The harness never creates provider accounts or enters credentials.

- `provider` found and `productionUrl` null → ask once: `Production URL for <provider>?`
- `provider` found and `productionUrl` set → say it in one line and ask nothing.
- `provider` is `none` → ask once: `Where does this deploy? (a) existing — tell me the provider and production URL (b) none — skip verification (c) build one: pick a plan or type your own`
  - (a) → record the provider and URL.
  - (b) → record `provider: none`; change it later with `/dts2-harness:evolve deploy`.
  - (c) → show `PRODUCTION_PLANS` from `deploy-detect.py` for the stack signal that fits the repo (`nextjs`, `react` or `static` → vercel, cloudflare-pages; `node-api`, `python-api` or `docker` → fly, render; `supabase` → vercel; `workers` → cloudflare) and accept a free-text plan line. Write the chosen or typed plan to the end state as `deploy.plan: <text>` with `deploy.provider` and `deploy.status: planned`.

Record the answer for the end state's `deploy:` block. A `planned` deploy is built by `run` as its own run before any feature run; see **Deployment verification** in the run skill.

### Round 2b — Other harnesses

Skip with no message if the repo is greenfield or scout listed nothing besides `CLAUDE.md`, `AGENTS.md` and `.agents`.

`CLAUDE.md` and `AGENTS.md` are always read and never rewritten; do not ask about them. `.agents/` is not a harness: it holds marketingskills' shared context, so ignore it here even when scout lists it. For each other folder scout listed (`.omc`, `.flow`, `.beads`, `.conductor`, `.agent`, `.impeccable`), ask once:

> I found `<folder>` from another tool. Should I **import** it (read its specs and plans as input to the end state, leaving it untouched), **coexist** with it (leave it alone; agents may read it, never write to it), or **retire** it (import it, then move it to `.harness.bak-<stamp>/<folder>` because you no longer use that tool)? If you're not sure, I'll coexist.

- No answer or an unclear answer → `coexist`.
- `import` → read its specs, plans and state now and use them to pre-fill components and answers (an `.omc/specs/deep-interview-*.md` maps almost field for field; `.flow/` plans map to components). Tell the user what you took from it.
- `retire` → treat as import now; the move happens in Part 2, after approval.

Record each folder and decision for the end state's Other harnesses table.

### Round 2c — Agents

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" detect --project <repo>`.

- `claudeOnly: true` → the roster is `[claude]`. Say one line and ask nothing: `Agents: only Claude is installed, so Claude fills every role.`
- Otherwise → propose a roster from `installed`, giving each agent the default `roles` from its profile in `${CLAUDE_PLUGIN_ROOT}/profiles/agents/<name>.json`. Show it as a short list (`claude: lead, verifier, builder, reviewer`, `codex: builder, second-opinion`) and ask once: use this roster, or change it? Claude must stay in the roster as lead.

Auth mode comes from `detect`'s `auth` map (subscriptions first, API keys by opt-in). Never print an environment variable's value and never read credential files.
- `auth: subscription` (the CLI is already logged in) → include the agent with no further prompt: no second authentication, no API-key question. Record `auth: subscription`.
- `auth: api-key` (no subscription login found, but the profile's `apiKeyEnv` is set) → ask one line per agent, for example: `codex has no subscription login; an API key is present (pay-per-use). Include or exclude?` Record `included: true` or `included: false`, and `auth: api-key`.
- `auth: installed (unverified)` (the CLI is installed but has no login check: gemini, grok, opencode) → ask once per agent: `<agent> is installed, but I can't check its login. Is it logged in to your subscription? (y/n)`. Yes → record `auth: subscription`. No → if `detect`'s `apiKey[<agent>]` is true, ask the pay-per-use line above; otherwise list it as not available with its login step (`agy` / open Antigravity for gemini, `grok login`, `opencode auth login`) and leave it out of the roster.

Gemini is reached through the Antigravity CLI, so its binary is `agy`, not `gemini`.

If `detect` reports an agent as not available but the user says its CLI is installed, it is off the PATH the harness sees (common on Windows, WSL, and npm- or bun-global installs). Do not drop it — tell the user to either add its folder to `searchPaths` in its profile, or set `DTS2_BIN_<NAME>` (e.g. `DTS2_BIN_AGY` or `DTS2_BIN_GROK`) to the binary's full path (or its folder) and re-run detect. Record the resolved path as a Decisions action item so later runs keep finding it.
- `auth: none` → list the agent as not available with its login command (the login counterpart of its `statusCommand`, e.g. `codex login`). Do not add it to the proposed roster and do not ask anything.
- Handoff (IDE) agents are included as before; their login cannot be checked.

Roster entries carry the choices: `- name: codex`, then `auth: api-key` and `included: false` on the lines under it. `roster.py probe` drops an `included: false` agent as `excluded by user`.

Record the chosen roster for Part 2.

### Round 3 — Topology

1. If you don't yet know what the user is building or changing, ask: `In a sentence or two, what are you building or changing?` Greenfield: from the answer, note whether it will have a UI and a marketing surface (landing or pricing page); if that is unclear, ask once. This stands in for scout's `Marketing surface:` line in Part 2.
2. Propose 1 to 6 top-level components (from scout's modules, imported specs, and the answer above). One line each: name and what it does.
3. Ask the user to confirm, merge, split, or defer any of them. Deferred components go to Non-goals.
4. When the user confirms, say `Components locked.` and list them. After this, add or remove a component only if the user asks.
5. Workspace mode only: mark each component with the repo that owns it, or `cross-repo` when it spans repos. Then ask once: `Which repo must ship first, and what shared surfaces must stay in sync?` From the answer record `depends_on` per repo, `contracts` (name, owner, consumers) and `release_order`. Never guess them; anything the user leaves out goes to Open questions.
6. Blueprint: after components are locked, record a `## Blueprint` block for the end state, one row per layer: data model, api surface, screens/routes, auth, infra/deploy, observability, background jobs. Ask once for the choice per layer (propose from scout's findings); `n/a` is allowed with a status of `n/a`. Never invent a choice the user did not give.

### Round 3b: 3b. Sections (end to end)

Runs right after the Blueprint step. Walk the project from entry to ship and fill the end state's `## Sections` table completely, one row each: data model, API surface, each screen/route, auth, background jobs, integrations, infra/deploy, observability, tests, docs, and GTM surface. Order the rows by dependency; give each its `serves component`, `files / area`, `depends on` (row numbers or `-`) and `complexity` (`mechanical`, `normal` or `design`). New rows start as `todo`.

- Brownfield: areas that already exist and work get `status: done`.
- Every component in the Blueprint and Topology must have at least one section. Say which blueprint layers have no section and ask whether that is intentional; an intentional gap is recorded under Assumptions.
- Ask the user once to confirm or edit the map: `Here is the end-to-end map, N sections. Edit, or approve?` Apply edits and ask again only if the change is structural.
- Clarity gate (feeds the Round 4 ratings, and the `## Done` check before approval): a map with an unmapped blueprint layer, or any section without `files / area` or `depends on`, caps clarity. Apply the existing clarity-score rule for missing fields: omit the `success` key from the ratings of every component such a section serves, so it scores 0 and bounds the overall clarity until the map is fixed. Do not change `clarity-score.py`.

### Round 4 — Question loop

Read the threshold from `end_state_threshold` in `.claude/dts2-harness.local.md`. If the file or key is missing, use 80 and record `thresholdSource: default`; otherwise record `thresholdSource: local`.

Each round:
1. Rate every component from 0 to 100 on each dimension, using only what the user has said and what you have read. Do not inflate. Guide: 0 nothing known, 50 stated but vague, 80 specific and checkable, 100 nothing left to ask.
   - `goal` — what it must do.
   - `constraints` — limits it must respect (stack, performance, security, budget, deadlines, must-not-change).
   - `success` — how we'll know it works (acceptance criteria someone can check).
   - `context` (brownfield only) — how it fits the existing code.
2. Write the ratings to a temp file outside the repo (`mktemp`), shaped as
   `{"mode":"brownfield","components":[{"name":"...","goal":0,"constraints":0,"success":0,"context":0}]}`
   (greenfield: `"mode":"greenfield"` and no `context` key),
   and run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/clarity-score.py" <file>`. It returns `clarity`, `weakest.component`, `weakest.dimension`.
3. Start your message with `Clarity: NN%` (the returned `clarity`).
4. If `clarity` is at or above the threshold, stop the loop.
5. Otherwise ask **one** question aimed at `weakest.component` and `weakest.dimension`. Name the component, ask in plain words, and offer two or three example answers when that helps. For example, for success on "billing": `Billing — how will we know it works? For example: "an invoice PDF matches the order total", or "a failed card retries 3 times then emails the customer".`
6. Fold the answer into your record and start the next round.

Ways out of the loop:
- The clarity reaches the threshold.
- The user replies with the literal text `Continue anyway`. Nothing else counts; if they say something similar, tell them that typing `Continue anyway` ends the interview below the threshold. Record `continuedAnyway: yes (at NN%)`.
- 20 rounds. Stop, say so, and list what is still unclear under Open questions.

### Round 4b — Skills

Runs after the loop and before Round 5, when every component and its acceptance criteria are known. Search; do not install anything yet.

1. Search per component, first option that works:
   - the `find-skills` skill, if present, in search mode;
   - else `npx skills find <component>`;
   - else say `No skill search available; skipping skills.` and go to Round 5.
2. Show at most 3 skills per component, each with its source and a one-line reason.
3. Ask once which to install **for this project only**. On yes, run `npx skills add <source> --skill <name>` from the repo root, which installs into the project (`.claude/skills/`); for a plugin, add it to `enabledPlugins` in the project's `.claude/settings.json`. Never pass `-g` and never install into the user's home folder.
4. Build the **skill plan**: one row per proposed skill, installed or not, with the columns `skill | source | installed | serves component | phase | order`. Phase is `plan`, `build`, `review` or `verify`. Order is the order a builder uses them within that component. Declined skills stay in the table with `installed: no`.

### Round 4c — 4c. Grill the draft

Runs after the interview loop (and Round 4b) ends and before Round 5's approval question. Install each companion skill only at this step, with `npx skills add https://github.com/mattpocock/skills --skill <name>` (see Companion skills in `.harness/discipline.md`), and record it in `.harness/keep.yaml` → `skills:` as `- name: <name>` / `source: npx skills add https://github.com/mattpocock/skills --skill <name>` / `serves: harness`. Invoke it by slash name with the Skill tool, or read its SKILL.md and follow it inline when headless. If `npx` is unavailable or the install fails, print `Skill <name> not installed (npx unavailable or offline); continuing without it.`, add a Decisions action item with the command, and continue.

Install and run `/grill-me` against the draft end state (components, Done criteria, Blueprint, Sections). Fold its hard questions into the interview as one more round of answers; unresolved ones go to Open questions. Then proceed to Round 5.

### Round 5 — Write the end state and ask for approval

1. Copy `${CLAUDE_PLUGIN_ROOT}/templates/end-state.md` to `.harness/end-state.md` and fill it:
   - metadata: `rounds`, `clarity`, `threshold`, `thresholdSource`, `roster`, `status: pending approval`, `continuedAnyway` (`no`, or `yes (at NN%)`);
   - Related repos (url, role, tag, note), Other harnesses (folder, decision), Skills (the skill plan table), Topology, Blueprint, Sections (the confirmed map from Round 3b), Goal, Constraints, Non-goals, Acceptance criteria per component as `- [ ]` items, Assumptions, Open questions;
   - Deploy (the `deploy:` block from the Deploy target step: `provider`, `productionUrl`, `checkCommand`, and for a planned deploy `plan` and `status: planned`).
2. Workspace mode: first ask once where the workspace manifest and root end state should live (default: the common parent folder of the linked repos). Then write one `.harness/end-state.md` per linked repo with only that repo's components, and a root `end-state.md` in that folder with the `cross-repo` components plus the `depends_on`, contracts and release order from Round 3. Every one of them starts as `status: pending approval`.
3. Show a short summary (components, clarity, open questions) and every file path, then ask once: `Approve this end state? Reply "approve", or tell me what to change.` In workspace mode this one approval covers all the files.
4. On changes, edit the files and ask again. On the first `yes`/approval, do not mark anything approved yet; continue with 5b.
5. **5b. Architecture pass.** Install and run `/improve-codebase-architecture`: brownfield, against the repo(s); greenfield, against the Blueprint and Sections as the planned architecture. Present its findings as proposed amendments to the end state (sections added, split or reordered, blueprint lines changed). Ask once: `Apply these architecture amendments? (y/n/edit)`. On yes, rewrite end-state.md and ask the approval question again (`Approve this end state? Reply "approve", or tell me what to change.`).
6. **5c. Agent-friendly rewrite.** After that second sign-off, install and run `/writing-for-agents` on `end-state.md` and on the plan wording the lead will consume, derived from `${CLAUDE_PLUGIN_ROOT}/templates`; write the rewritten plan guidance to `.harness/plan-style.md` (the lead reads it when present). The rewrite changes form, never facts: show a diff summary and write it only after the user confirms with one yes.
7. Set `status: approved` in every file only after 5c. Then go to Part 2. The three installs (grill-me, improve-codebase-architecture, writing-for-agents) are each recorded in `.harness/keep.yaml` as described in Round 4c.

## Questions from the user

When the user asks a question rather than giving an instruction ("why", "should we", "what's the difference", "is X better"), install and run `/ask-matt` (see Companion skills in `.harness/discipline.md`) with the question and the harness context (end state, current phase) before answering, and base the reply on its answer. If you are still unsure afterwards (the answer is hedged, depends on facts you do not have, or the user says it is not sufficient), install and run `/research` on the question and report the findings with sources before answering. A missing install never blocks: print `Skill <name> not installed (npx unavailable or offline); continuing without it.`, add a Decisions action item with the command, and answer as best you can.


## Part 2 — Scaffold

Gate: `.harness/end-state.md` has `status: approved`, or the user passed `--scaffold-only`.

### Single
1. Confirm the repo root and that `.git` exists (warn if not). With `--scaffold-only`, dispatch `dts2-harness:scout` now for its `Harnesses:` and `Marketing surface:` lines; every harness it finds is treated as `coexist`.
2. If `.harness/config.yaml` exists, ask: back up `.harness/` to `.harness.bak-<timestamp>/` and rewrite, merge missing keys only, or abort. (`end-state.md` is never overwritten here.)
3. Detect the stack from root files (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json`, workspace markers such as `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `go.work`).
4. For each harness the user chose to retire: move it to `.harness.bak-<stamp>/<folder>`. Leave `coexist` folders untouched.
5. Write:
   - `.harness/config.yaml` — `project`, `commands` (`test`, `typecheck`, `lint`, `build`, `quick`) taken from real scripts only, `paths` (src, tests, docs, config, generated), `do_not_touch` (`.env`, `.env.*`, `secrets/**`, `**/credentials*`), and a `roster:` block from the Agents round (default `- name: claude`; with `--scaffold-only`, run `roster.py detect` and use the default unless other agents are installed, then ask once). For a monorepo add `packages:` with each package path and its own commands.
   - `.harness/review-checklist.md` — correctness, types, tests, security, conventions, scope, tuned to the stack.
   - `.harness/lessons.md` — header only: `# Lessons` and one line explaining the format `- [L-001] <rule> (source: <run or PR>)`.
   - `.harness/discipline.md` — copy `${CLAUDE_PLUGIN_ROOT}/templates/discipline.md`.
   - `.harness/keep.yaml` — copy `${CLAUDE_PLUGIN_ROOT}/templates/keep.yaml` if absent; fill `agents:` from the Agents round and append every skill the user said yes to in the Skills round under `skills:` with its `source` (`npx skills add <ref>` exactly as installed, `plugin`, or `synced`) and `serves`. Any plugin the user names as must-keep goes under `plugins:`. Append only; never remove entries. It is committed with the harness and never gitignored.
   - `.harness/state.md` — copy `${CLAUDE_PLUGIN_ROOT}/templates/state.md` if absent. Append each harness decision from Round 2b as `- <date> <folder>: <decision>`.
   - `.claude/dts2-harness.local.md` — copy `${CLAUDE_PLUGIN_ROOT}/templates/dts2-harness.local.md`.
   - `.agents/product-marketing-context.md` — a stub with headings (product, audience, positioning, pricing, voice), **only** if the repo has a marketing surface (scout's `Marketing surface: yes` for brownfield, the user's stated surface for greenfield) and the file does not exist. This is marketingskills' shared context file and the one file the harness may write under `.agents/`.
6. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" resolve --config .harness/config.yaml`. If it errors, show the error and fix the roster with the user.
7. If the Impeccable skill is installed and the repo has a marketing surface (as in step 5) or a UI (a frontend framework, HTML templates, or app screens in the stack; for greenfield, the user's stated surface), run `/impeccable init`.
8. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-ignored.py" <repo>` to add the harness's ignore entries to `.gitignore`.
8b. Give every detected agent its own project memory file, seeded from one shared source: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent-memory.py" --write <repo> --agents <installed agents from roster.py detect, comma-separated>`. It writes each distinct `rulesFile` (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, ...) when absent; when the file exists it appends only a managed block between `<!-- dts2-harness:start -->` and `<!-- dts2-harness:end -->`, once, and never touches the rest. A second run changes nothing. It runs before step 9, so the managed block already carries the pointer line and step 9 adds nothing twice.
9. Create `AGENTS.md` if absent and append this line once if it is not already there: `Harness state for any agent: .harness/handoff/latest.md (resume with /dts2-harness:run resume).` Change nothing else in the file.
10. Show the detected commands once and let the user correct them. Tell the user `config.yaml`, `review-checklist.md`, `lessons.md`, `discipline.md`, `state.md` and `end-state.md` are meant to be committed.

### Batch (parallel, scaffold-only)
1. Resolve the repo list. For a folder, list its immediate children that contain `.git`.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo-size.py" --json <repo...>` to show size and tier per repo.
3. Dispatch one general-purpose subagent per repo in a single message (cap at 8 per wave; run more waves if needed). Each gets the Single steps above with `--scaffold-only` and its repo path, and writes only inside its own repo. Subagents never ask the user anything: an existing `.harness/config.yaml` means merge missing keys only, the roster is the default `- name: claude`, `.harness/keep.yaml` is copied from the template when absent and never rewritten when present, and each such choice (backup, roster when other agents are installed) comes back as an open item.
4. Collect results into one table: repo, stack, commands found, commands missing, open items, warnings.
5. Resolve missing commands and open items with the user in one pass at the end, not per repo.

### Workspace
One interview covers the whole workspace; Round 5 already wrote and got approval for every per-repo end state and the root end state.
1. Scaffold each repo as in Batch.
1b. Write the workspace keep list next to the manifest: `<workspace root>/.harness/keep.yaml` from `${CLAUDE_PLUGIN_ROOT}/templates/keep.yaml`, filled with the Agents round roster, every skill the user said yes to (with its exact install source), and any plugin named as must-keep. Member repos keep their own `.harness/keep.yaml` from the Batch step; a re-run reads the root one first, then each member's, and never re-asks about anything listed in either.
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

## Guardrails
- Never scaffold before the end state is approved, unless `--scaffold-only` was given.
- Never overwrite existing config without the user's choice.
- Never guess commands. Leave them empty and say so.
- Never write into a context repo, a `coexist` harness folder, `CLAUDE.md` or `AGENTS.md`, except the single pointer line and the managed block that `agent-memory.py` writes in Part 2 (Single).
- Never install skills outside project scope.
- Never commit or push.
