# setup - Part 1, the interview (first rounds: repos, deploy target, other harnesses, agents)

## Part 1 — Interview

Rules for the whole interview:
- Ask **one question per message**. Plain words, no jargon, no internal names like "dimension" or "weakest".
- Until the end state is written, the only writes are the temporary ratings file (outside the repo) and any skill installs the user says yes to.
- Keep a running record as you go: mode (greenfield or brownfield), related repos, harness decisions, roster, components, answers, rounds, clarity.

### Round 1 — Greenfield or brownfield

1. Look at the repo root. **Greenfield** if there is no source code yet (empty, or only README, LICENSE, `.gitignore`, config stubs). Otherwise **brownfield**.
2. Brownfield: dispatch the `dt:scout` agent on the repo and keep its output. You need its `Harnesses:` line, its `Marketing surface:` line, and the stack and modules it reports. Also read any existing `.harness/` files (config, lessons, state) for context.
   A scout report whose first line is `PARTIAL: hit turn cap at <step>` is incomplete: re-dispatch the scout with a narrower scope or a fresh agent before using its output.
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
  - (b) → record `provider: none`; change it later with `/dt:evolve deploy`.
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
- `auth: installed (unverified)` (the CLI is installed but has no login check: gemini, grok, opencode, muse) → ask once per agent: `<agent> is installed, but I can't check its login. Is it logged in to your subscription? (y/n)`. Yes → record `auth: subscription`. No → if `detect`'s `apiKey[<agent>]` is true, ask the pay-per-use line above; otherwise list it as not available with its login step (`agy` / open Antigravity for gemini, `grok login`, `opencode auth login`, `muse login`) and leave it out of the roster.

Gemini is reached through the Antigravity CLI, so its binary is `agy`, not `gemini`.

If `detect` reports an agent as not available but the user says its CLI is installed, it is off the PATH the harness sees (common on Windows, WSL, and npm- or bun-global installs). Do not drop it — tell the user to either add its folder to `searchPaths` in its profile, or set `DTS2_BIN_<NAME>` (e.g. `DTS2_BIN_AGY` or `DTS2_BIN_GROK`) to the binary's full path (or its folder) and re-run detect. Record the resolved path as a Decisions action item so later runs keep finding it.
- `auth: none` → list the agent as not available with its login command (the login counterpart of its `statusCommand`, e.g. `codex login`). Do not add it to the proposed roster and do not ask anything.
- Handoff (IDE) agents are included as before; their login cannot be checked.

Roster entries carry the choices: `- name: codex`, then `auth: api-key` and `included: false` on the lines under it. `roster.py probe` drops an `included: false` agent as `excluded by user`.

Record the chosen roster for Part 2.

### Skill parity

Once that roster is final, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lead_skills.py" gaps --agents <names> --home "$HOME"` with the included agent names, comma-separated. Claude is the orchestrator and is never behind. For every agent in `behind`, say one line: `<agent> is behind the orchestrator: <reason>.` Then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lead_skills.py" sync --agents <those names> --home "$HOME"`. The sync is silent: do not ask, and do not list the files it wrote. An agent left out of the roster is not updated.
