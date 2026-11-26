> Directory edition: do not run bundled scripts or hooks, a package launcher, or a download piped into a shell. Do not read tokens or credential files from the machine. Carry out the step with Read, Edit, Grep, Glob, and git or gh, and write the files the step names.

# setup - Part 1, the interview (topology, sections, question loop, skills, grill, end state)

### Round 3 — Topology

1. If you don't yet know what the user is building or changing, ask: `In a sentence or two, what are you building or changing?` Greenfield: from the answer, note whether it will have a UI and a marketing surface (landing or pricing page); if that is unclear, ask once. This stands in for scout's `Marketing surface:` line in Part 2.
2. Propose 1 to 6 top-level components (from scout's modules, imported specs, and the answer above). One line each: name and what it does.
3. Ask the user to confirm, merge, split, or defer any of them. Deferred components go to Non-goals.
4. When the user confirms, say `Components locked.` and list them. After this, add or remove a component only if the user asks.
5. Workspace mode only: mark each component with the repo that owns it, or `cross-repo` when it spans repos. Then ask once: `Which repo must ship first, and what shared surfaces must stay in sync?` From the answer record `depends_on` per repo, `contracts` (name, owner, consumers) and `release_order`. Never guess them; anything the user leaves out goes to Open questions.
6. Blueprint: after components are locked, record a `## Blueprint` block for the end state, one row per layer: data model, api surface, screens/routes, auth, infra/deploy, observability, background jobs. Ask once for the choice per layer (propose from scout's findings); `n/a` is allowed with a status of `n/a`. Never invent a choice the user did not give.
7. Greenfield only: now ask the deploy-target question you deferred in Round 2. Read the "Round 2 (continued) — Deploy target" section of `phase-1-interview-a.md` (same folder) and run it here, once you know what is being built. Brownfield already did it in Round 2.

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
   - else `the publisher's skill installer find <component>`;
   - else say `No skill search available; skipping skills.` and go to Round 5.
2. Show at most 3 skills per component, each with its source and a one-line reason.
3. Ask once which to install **for this project only**. On yes, run `the publisher's installer for <source> --skill <name>` from the repo root, which installs into the project (`.claude/skills/`); for a plugin, add it to `enabledPlugins` in the project's `.claude/settings.json`. Never pass `-g` and never install into the user's home folder.
4. Build the **skill plan**: one row per proposed skill, installed or not, with the columns `skill | source | installed | serves component | phase | order`. Phase is `plan`, `build`, `review` or `verify`. Order is the order a builder uses them within that component. Declined skills stay in the table with `installed: no`.

### Round 4c — 4c. Grill the draft

Runs after the interview loop (and Round 4b) ends and before Round 5's approval question. Install each companion skill only at this step, with `the publisher's installer for https://github.com/mattpocock/skills --skill <name>` (see Companion skills in `.harness/discipline.md`), and record it in `.harness/keep.yaml` → `skills:` as `- name: <name>` / `source: the publisher's installer for https://github.com/mattpocock/skills --skill <name>` / `serves: harness`. Invoke it by slash name with the Skill tool, or read its SKILL.md and follow it inline when headless. If `a package launcher` is unavailable or the install fails, print `Skill <name> not installed (a package launcher unavailable or offline); continuing without it.`, add a Decisions action item with the command, and continue.

Install and run `/grill-me` against the draft end state (components, Done criteria, Blueprint, Sections). Fold its hard questions into the interview as one more round of answers; unresolved ones go to Open questions. Then proceed to Round 5.

### Round 5 — Write the end state and ask for approval

1. Copy `${CLAUDE_PLUGIN_ROOT}/templates/end-state.md` to `.harness/end-state.md` and fill it:
   - metadata: `rounds`, `clarity`, `threshold`, `thresholdSource`, `roster`, `status: pending approval`, `continuedAnyway` (`no`, or `yes (at NN%)`);
   - Related repos (url, role, tag, note), Other harnesses (folder, decision), Skills (the skill plan table), Topology, Blueprint, Sections (the confirmed map from Round 3b), Goal, Constraints, Non-goals, Acceptance criteria per component as `- [ ]` items, Assumptions, Open questions;
   - Deploy (the `deploy:` block from the Deploy target step: `provider`, `productionUrl`, `checkCommand`, and for a planned deploy `plan` and `status: planned`).
   - Production readiness: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/app-type-detect.py" <repo>` (greenfield or `unknown`: pass `--type` with the type the Topology implies, one of `web-app`, `api`, `cli`, `library`, `static-site`). Say the detected type in one line and let the user correct it. Set `appType:` to it and replace the placeholder table with the output of the same command with `--table`. Rows that do not apply to the type are already `n/a`; never turn an `n/a` row into a gate, and never add a report row as a gate.
2. Workspace mode: first ask once where the workspace manifest and root end state should live (default: the common parent folder of the linked repos). Then write one `.harness/end-state.md` per linked repo with only that repo's components, and a root `end-state.md` in that folder with the `cross-repo` components plus the `depends_on`, contracts and release order from Round 3. Every one of them starts as `status: pending approval`.
3. Show a short summary (components, clarity, open questions) and every file path, then ask once: `Approve this end state? Reply "approve", or tell me what to change.` In workspace mode this one approval covers all the files.
4. On changes, edit the files and ask again. On the first `yes`/approval, do not mark anything approved yet; continue with 5b.
5. **5b. Architecture pass.** Install and run `/improve-codebase-architecture`: brownfield, against the repo(s); greenfield, against the Blueprint and Sections as the planned architecture. Present its findings as proposed amendments to the end state (sections added, split or reordered, blueprint lines changed). Ask once: `Apply these architecture amendments? (y/n/edit)`. On yes, rewrite end-state.md and ask the approval question again (`Approve this end state? Reply "approve", or tell me what to change.`).
6. **5c. Agent-friendly rewrite.** After that second sign-off, install and run `/writing-for-agents` on `end-state.md` and on the plan wording the lead will consume, derived from `${CLAUDE_PLUGIN_ROOT}/templates`; write the rewritten plan guidance to `.harness/plan-style.md` (the lead reads it when present). The rewrite changes form, never facts: show a diff summary and write it only after the user confirms with one yes.
7. Set `status: approved` in every file only after 5c. Then go to Part 2. The three installs (grill-me, improve-codebase-architecture, writing-for-agents) are each recorded in `.harness/keep.yaml` as described in Round 4c.

## Questions from the user

When the user asks a question rather than giving an instruction ("why", "should we", "what's the difference", "is X better"), install and run `/ask-matt` (see Companion skills in `.harness/discipline.md`) with the question and the harness context (end state, current phase) before answering, and base the reply on its answer. If you are still unsure afterwards (the answer is hedged, depends on facts you do not have, or the user says it is not sufficient), install and run `/research` on the question and report the findings with sources before answering. A missing install never blocks: print `Skill <name> not installed (a package launcher unavailable or offline); continuing without it.`, add a Decisions action item with the command, and answer as best you can.
