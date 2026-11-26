---
name: dt-feature
description: "Add a feature to the roadmap and update every plan to match: scores clarity, interviews when unclear, has the lead write it into the end state with acceptance criteria, and opens a plan PR. Use for add a feature or put this on the roadmap."
disable-model-invocation: true
---

## Cursor procedure

Find the plugin root: the nearest ancestor of this file that contains `.cursor-plugin/plugin.json`. The examples below say `$PLUGIN` for that directory.

Run `python3 "$PLUGIN/scripts/dt_gate.py"` for every gate. Exit 2 from `scaffold`, `preflight`, or `approve` stops the command. Exit 2 from `bridge` that prints `BLOCKED unsupported-runtime-script` is a precise blocker for that one step: record it and do not imitate the script. The interview, `approve`, and `scaffold` still run.

`--yes`, `--ship`, and `--scaffold-only` are rejected. A JSON key with the same name as a kind is not authorization. `approve` records the sha256 of the file the user accepted, and later gates require that digest.

Phase files for this command are in `$PLUGIN/skills/dt-feature/`.

Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls are `CURSOR_UNSUPPORTED` even after a permission phrase is recorded.

> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# Feature — from idea to planned sections, every plan in sync

`/dt-feature <description>` plans a feature; it does not build it. Building is `/dt-run section <#>` or `/dt-autopilot <#…>` afterwards.

## 1. Pre-check and scope
1. Run the run skill's **Pre-check (every run command)** exactly as written there. An upgrade it starts stops here; the handoff records `Next action: /dt-feature <description>`.
2. `python3 "$PLUGIN/scripts/dt_gate.py" bridge scope-check.py .` → use the workspace root when it says `workspace-member`. No `.harness/end-state.md` → say `No end state yet; /dt-setup interviews to one.` and stop: a feature needs an approved end state to land in.
3. Read `.harness/end-state.md` (Goal, Constraints, Non-goals, Blueprint, Sections, Acceptance criteria, Open questions), `.harness/config.yaml` `paths.docs`, `.harness/action-items.md`, and every plan-like doc the repo keeps (from `paths.docs`, plus any of `PLAN.md`, `ROADMAP.md`, `STATUS.md`, `BRAINSTORM.md`, `docs/roadmap*`, `docs/**/plans/*` that exist). Record which ones exist; they are the plans to keep in sync.
4. **Conflict check.** The feature contradicts a Non-goal or Constraint → quote it and ask once: change the end state (the feature overrides it) or drop the feature. It duplicates an existing component or section → say which and ask: extend that one, or stop.

## 2. Clarity, then the deep interview only when needed
1. Rate the feature as one component (or several, when it plainly spans layers) on the setup skill's Round 4 dimensions (`goal`, `constraints`, `success`, and `context` for a brownfield repo), from the description and the repo only. Do not inflate. Write `{"mode":"<greenfield|brownfield>","components":[…]}` to a temp file outside the repo and run `python3 "$PLUGIN/scripts/dt_gate.py" bridge clarity-score.py <file>`.
2. Threshold: `end_state_threshold` from `.claude/dts2-harness.local.md`, default 80. Start the message with `Clarity: NN%`.
3. **At or above the threshold** → go to step 3 (no interview).
4. **Below it** → run the deep interview scoped to this feature, using the setup skill's Part 1 rules verbatim, limited to the new component(s):
   - **Round 3b. Sections** for the feature: each section with `files / area`, `depends on` (existing section numbers allowed), `complexity`, status `todo`; a section with no `files / area` or `depends on` caps clarity exactly as Round 3b says.
   - **Round 4 — Question loop**, one question per round at `weakest.component` / `weakest.dimension`, until the threshold, the literal `Continue anyway`, or 20 rounds.
   - **Round 4b — Skills** for the new component only.
   - **Round 4c. Grill the draft** with `/grill-me` on the feature's draft (component, Done criteria, Blueprint lines, Sections).
5. Every answer goes into the record; anything unresolved goes to Open questions with the feature's name.

## 3. Lead writes the plan change
Dispatch `dt:lead` (seat: sign-off, `model: opus`) with the feature record, the current end state, `.harness/plan-style.md` if present, and the list of plan docs. Tell it to return, as one patch, without touching code:
- **end-state.md**: the component under Topology; its `- [ ]` acceptance criteria under Acceptance criteria; Blueprint rows changed or added with status; new rows in `## Sections` numbered after the last existing one, with `depends on` pointing at real section numbers; Constraints, Non-goals, Assumptions and Open questions as the interview settled them; Skills rows for new skills. Existing sections and approved criteria are never renumbered, rewritten or removed.
- **Each repo plan doc** that exists: the feature added in that doc's own format and place (a roadmap entry, a phase task, a status line `planned`), never a reformat of the rest.
- **action-items.md**: a Decisions row for each open question, a Secrets row (name only, via `action-items.py <repo> add Secrets NAME`) for each new secret the feature needs, a Deploy row for each external setup step.
- `## Done` for the feature: one checkable outcome per line.
A lead report whose first line is `PARTIAL: hit turn cap at <step>` is not a patch: do not show it for approval; re-dispatch the lead with a narrower scope or a fresh agent, inside the fix-loop cap.

## 4. Architecture and agent-friendly passes, then approval
1. **5b. Architecture pass.** Run `/improve-codebase-architecture` against the repo with the new sections as the planned change; present its findings as amendments to the patch and ask `Apply these architecture amendments? (y/n/edit)`.
2. Show the patch as a diff summary (end state, each plan doc, action items), the new Sections rows, the Done list and the clarity, and ask once: `Add this feature to the plan? Reply "approve", or tell me what to change.` On changes, revise with the lead and ask again. Silence means stop.
3. **5c. Agent-friendly rewrite.** After approval, run `/writing-for-agents` on the new end-state text only; it changes form, never facts; apply after one yes.
4. In autopilot, steps 2 and 3's questions are answered by the autopilot consensus gate instead of the user (see the autopilot skill).

## 5. Land it
1. Branch `feature/<slug>` from `origin/<base>` (`dev` when it exists, else the default branch), write the approved patch, keep `status: approved` on the end state with a `- <date> feature <slug> added: sections <#…>` line in `.harness/state.md` → `## Decisions`.
2. Ship it: run `/dt-ship` (its pre-check, checks, receipt and PR); the PR's Linked work names the feature slug and the new section numbers.
3. Refresh the handoff: `python3 "$PLUGIN/scripts/dt_gate.py" bridge handoff-write.py <repo>`.
4. End with one line naming what to run next: `/dt-run section <first new #>` or `/dt-autopilot <#,#,…>`.

## Guardrails
- Planning only: no code, no migrations, no installs beyond the companion skills.
- Never renumber, rewrite or delete approved sections or criteria; only add, or change what the user explicitly approved.
- Questions one at a time, never more than one per message.
- Never print a secret's value; secrets are names only.
