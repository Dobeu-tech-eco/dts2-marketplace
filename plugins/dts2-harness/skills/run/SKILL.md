---
name: run
description: Run the dts2 plan-build-review-verify pipeline on a task in one repo or a multi-repo workspace. Sizes the team from the repo and task, checks which agents are available and what they cost, plans against the approved end state, builds with parallel builders on separate file sets, reviews and walks the changed screens, and ends with a receipt. Two human checkpoints (plan, ship). Also `run add secret NAME` to close a deferred secret. Use when the user asks to run the harness, harness a task, or do a multi-file, cross-package, or cross-repo change with rigor.
---

# Run — plan, build, review, verify, ship

Follow the phases in order. Every agent dispatch uses the Agent tool with `subagent_type: dts2-harness:<role>` and a `model` override taken from `roster.py model` (claude: `economy` → `haiku`, `standard` → `sonnet`, `frontier` → `opus`). The lead and the verifier always run on `frontier`.

If the request is `run add secret NAME`, skip to **Add secret mode**.

## Preflight
1. **Harness change.** If the request names a harness skill, agent, hook, or profile (a dts2-harness file, not the repo's own code), print `That changes the harness itself; use `/dts2-harness:evolve`.` and stop. Never plan a harness change as a repo task.
2. **Config and mode.** Look for `.harness/config.yaml` in the repo, then `.harness-workspace.yaml` in a parent folder. Neither → stop and point to `/dts2-harness:setup`. Print one mode line: `Mode: workspace` if `.harness-workspace.yaml` was found, else `Mode: single`.
3. **Ignore guard.** For each repo involved: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-ignored.py" <repo>`.
4. **End state.** If `.harness/config.yaml` exists and `.harness/end-state.md` does not, print exactly `No end state yet; /dts2-harness:setup interviews to one.` and continue.
5. **Settings.** Read `.claude/dts2-harness.local.md`: `auto_scale` (default true), `max_builders` (6), `max_reviewers` (4), `second_opinion` (none), `auto_learn` (true).
6. **Roster.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" resolve --config .harness/config.yaml`. On error, show it and stop. Keep the JSON.
7. **Clean tree.** `git status --porcelain` in every repo involved. If dirty, ask once: stash and restore after, build on top, or stop. Record `git rev-parse HEAD` per repo as the rollback point.
8. If the task is under 10 words or vague, ask one clarifying question.
9. Production deploys, data deletion, auth, or payments → confirm before anything else.

## Phase 0 — Size and Budget check
1. Dispatch `dts2-harness:scout` (`model: haiku`) with the repo path(s) and the task. Use its tier unless `auto_scale` is false (then tier S).
2. **Budget check** (`roster.py probe`). Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" probe --config .harness/config.yaml`. From its JSON:
   - Drop every agent in `dropped` for this run; keep its `reason`.
   - An agent with budget `low` keeps only the `second-opinion` role (the probe already restricts its `roles`); never give it a builder or reviewer seat.
   - Keep the probe JSON for the lead. Each agent carries `costTier` (1 cheapest).
   - Auth: each probe entry carries `auth` (`subscription`, `api-key`, or `none`). Agents already logged in via subscription are used as-is; never prompt for a second authentication or an API key. An agent is dispatched via API key only when its roster entry says `auth: api-key` and `included: true`.
3. Resolve models once per agent you may use: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" model --agent <name> --tier <economy|standard|frontier>`. `null` means use that agent's default model.

## Phase 1 — Plan (lead)
Dispatch `dts2-harness:lead` with `model` = claude `frontier` (`opus`). Give it: the task verbatim, `.harness/config.yaml`, `.harness/end-state.md`, `.harness/discipline.md`, `.harness/lessons.md`, the scout report, the roster JSON, the probe JSON, and the workspace manifest if present. Tell it:
- Assign only agents in the probe's `usable` list, by `costTier`: the cheapest available agent whose roles include the seat for builders rated `complexity: mechanical` and for axis reviews; the strongest for the plan, the verifier, and the final review.
- Rate every `### Builder N` with `complexity: mechanical|normal|design`.

**Plan checkpoint.** It will not open without the lead's `## Done` section with at least one line. If the section is missing or empty, send the plan back to the lead once with "Add the Done section: one outcome per line with its check method." Still missing → stop and say why.

Show, in this order:
- The plan as the lead wrote it, including `## Done` and `Axes:`.
- `Team: N builders on separate file sets`, reviewer axes, and one line per seat: `<role> — <agent> (<tier>, <auth>)`, where auth is `subscription` or `api-key`, for example `builder 2 — codex (standard, api-key)`.
- One line per dropped agent: `Dropped: <agent> — <reason>`.

Then say exactly: "Here is the plan, the done-criteria, and who does what. Approve, edit, or stop." Silence means stop. On edit, revise with the lead and show the checkpoint again. Any choice the user defers here goes to `.harness/action-items.md` → `## Decisions` as `| <item> | <context> | open |` (create the file from `${CLAUDE_PLUGIN_ROOT}/templates/action-items.md` if absent).

## Phase 2 — Build (parallel builders)
1. Builders = min(builder sections in the plan, scout's builder count, `max_builders`). In single mode every builder works in the same tree on its own file set. In workspace mode, or when the user opted in, follow **Workspace or opted-in isolation** below.
2. Model per builder from its `complexity`: `mechanical` → `economy`, `normal` → `standard`, `design` → `frontier`. A Claude builder is an Agent dispatch with that `model`. A live non-Claude builder runs through Bash as its profile `command` with the brief as the prompt, passing the resolved model when its CLI accepts one.
3. Dispatch every independent builder in one message so they run at once. Dependent builders start only after their dependencies report done.
4. **Handoff agents** (in the roster's `handoff` list): write `.harness/handoff/<agent>/<n>.md` (the builder's tasks, files, done-when) and the agent's rules file from its profile `rulesFile`, then pause that builder until the user says done.
5. A builder that asks for a file outside its file set: pause that builder and ask the user.
6. A builder that reports `SECRET NEEDED`: handle it as in **Secrets** below; the others keep going.
7. A builder failing 3 times on the same error: stop it, escalate with what failed, and record it in `.harness/state.md` under `## Failures and escalations`. Never retry blindly.
8. Run the integration task, if any, last. Show `git diff --stat` per repo.

### Secrets
A secret's value never passes through the chat, a prompt, or an agent's context. On a builder's `SECRET NEEDED: NAME — <what it unlocks> — <where consumed>` line, pause that builder only and ask once: **provide now** or **add later**.
- **provide now**: name the variable and exactly one place to put it: a `NAME=` line in `.env`, the project's secret manager command, or `gh secret set NAME` for CI. Wait for the user to say "done". Check presence only, never print a value: for `.env` or the environment, `test -n "${NAME:-}"` or `grep -qE '^NAME=.+' .env`; for GitHub Actions (`gh secret set NAME`), `gh secret list | grep -qE '^NAME\b'` (key names only). Present → resume the builder. Missing → say so and ask again once.
- **add later**: append `| NAME | <what it unlocks> | <where consumed> | <how to add> | open |` to `.harness/action-items.md` → `## Secrets` (create from the template if absent); add `NAME=` with a one-line comment to `.env.example`; let the builder keep its not-configured path. If any wiring was left undone because the secret is missing, write the status as `open, deferred wiring` and say what was deferred in `consumed in`.

The run continues either way. Open secrets appear in the receipt under *Steps outside this change*, and they never block the commit or the PR.

## Phase 3 — Review and verify
Take the run stamp once: `date +%Y%m%d-%H%M%S`. Pass it to every reviewer and verifier.
1. **Verifier walkthrough first**, when `Axes:` include `walkthrough`: dispatch `dts2-harness:verifier` (`model: opus`, one per repo touched) with the plan, the stamp, and the repo. Wait for its table; the reviewers need its screenshots and FAIL rows. Without the walkthrough axis, dispatch the verifier together with the reviewers in step 3.
2. **Critique report**, when `Axes:` include `critique`: if `/impeccable` is available, run `/impeccable critique` on the changed screens and save its report to `.harness/review/critique-<stamp>.md`. Otherwise the critique reviewer writes it, and you save its `### Critique` section to that same path.
3. Then dispatch the reviewers in parallel, in one message: one `dts2-harness:reviewer` per axis (tier S: one reviewer on all axes), capped at `max_reviewers`, each on its assigned agent at `standard`. Give each the diff, the plan, the stamp, and the critique report path when there is one. For `walkthrough-findings`, include the verifier's table.
4. Second opinion: for each usable agent holding `second-opinion` (or the `second_opinion` setting when it names an installed CLI), run its profile `command` with the review prompt and the diff through Bash. Mark its findings advisory.
5. **Final review.** After the axis reviews return, dispatch one `dts2-harness:reviewer` on the whole diff, all axes, at `frontier`, with the axis findings, to catch what crosses axes.

## Phase 3b — Finish pass
Runs only when `/impeccable` is available and the diff touched UI components named in `.harness/end-state.md`. If the diff touched such components and Impeccable is not installed, print one line, `Finish pass skipped: Impeccable not installed (github.com/pbakaus/impeccable)`, and go to Phase 4.

The builder that owns the files runs, inside its file set, in one dispatch:
- `/impeccable polish <components>` always (it consumes the critique's Fix list);
- `/impeccable harden <components>` when the diff touches data loading, network, or error paths;
- `/impeccable clarify <components>` when it touches error, empty, or confirmation states;
- `/impeccable optimize <components>` only when the walkthrough marked a screen slow.

One round, no loop. Then dispatch the verifier (`model: opus`) to run the configured tests on the result; its table replaces the earlier test rows.

## Phase 4 — Ship checkpoint
1. Merge findings, dedupe by file:line, keep the highest severity.
2. Build the receipt from `${CLAUDE_PLUGIN_ROOT}/templates/receipt.md` and save it to `.harness/runs/<stamp>/receipt.md`: tests run with pass/fail/skip counts from the verifier, review verdict, approver (left as the template placeholder until ship), steps outside this change (open secrets and decisions from `.harness/action-items.md`, handoff work), open risks, rollback point (the SHA recorded in preflight).
3. Show the receipt, findings by severity, the verifier verdict, and lesson candidates. Then say exactly: "Here is the receipt. Ship, fix the blocking items and re-check, or stop and revert."
- **Fix**: send only the CRITICAL and HIGH findings to the builders that own those files, then rerun Phase 3. Cap at 3 rounds. After 3, stop and escalate with what failed; record it in `.harness/state.md`.
- **Ship**: fill the receipt's `### Approved by` line with `$(git config user.name), $(date +%Y-%m-%d)` (ISO date), replacing the template placeholder; never create a PR from a receipt that still has it. Then do **After ship** below, then propose one commit message per repo and commit only on an explicit yes. Never push. When the user pushes and asks for a PR, create it with `gh pr create --body-file .harness/runs/<stamp>/receipt.md`; open secrets do not block it.
- **Stop and revert**: revert the run's changes the way the user picks, restore any stash.

Verifier BLOCKED means not done, unless the user explicitly overrides; the reason then goes in the commit message and `.harness/state.md`.

## After ship
Do these before the commit so they land in it. Do not narrate the writes.
1. Append the reviewers' lesson candidates to `.harness/lessons-inbox.md`. If `auto_learn` is not `false`, run the `learn` skill in its auto mode on those candidates and put the resulting `lessons.md` diff in the ship summary; no separate approval prompt.
2. In `.harness/end-state.md`, check the acceptance boxes the plan covered and the verifier confirmed, and update each touched component's status.
3. Append the ship decision to `.harness/state.md` → `## Decisions` as `- <date> <what shipped, receipt path>`.
4. Include `lessons.md`, `end-state.md`, `state.md`, `action-items.md` (if changed), and `.harness/review/critique-<stamp>.md` (if written) in the commit.

## Add secret mode
`run add secret NAME`:
1. Check presence only, as in **Secrets**: `test -n "${NAME:-}"`, `grep -qE '^NAME=.+' .env`, or `gh secret list | grep -qE '^NAME\b'` for a GitHub Actions secret; never print a value. Missing → name the one place to put it and stop.
2. Mark the `NAME` row in `.harness/action-items.md` → `## Secrets` as `done`.
3. If the row said `deferred wiring`, run Phase 0 to After ship with the task "Wire NAME into <consumed in>" and nothing else; both checkpoints apply. Otherwise say the secret is in place and stop.

## Status lines
Keep one block, updated as phases finish:
```
Mode   — single
Size   — tier M, 2 builders on separate file sets, reviewers: correctness, security
Budget — usable: claude, codex; dropped: gemini (not installed)
Plan   — waiting at the plan checkpoint
Build  — builder 1 done, builder 2 2/3, 1 secret deferred
Check  — verifier VERIFIED, 1 HIGH finding, finish pass done
Ship   — waiting at the ship checkpoint
```

## Workspace or opted-in isolation
Applies when the mode is `workspace`, or when `.claude/dts2-harness.local.md` sets `use_worktrees: always`. In single mode `use_worktrees` defaults to `never` (`auto` also means never there); builders share the tree on separate file sets.
- Workspace: builders are grouped per repo; contract owners build before consumers, following the manifest's `release_order`.
- Worktrees: for each builder run `git worktree add ../<repo>-dts2-<n> -b dts2/<n>` and give that builder only its worktree. Never when `use_worktrees: never`.
- Merge each builder's branch back into the working branch in plan order once it is done. A merge conflict stops the run and goes to the user.
- Handoff lanes in a workspace use `.harness/handoff/<agent>/<n>.md` inside the owning repo.
- On stop and revert, remove the dts2 worktrees and branches after reverting.

## Guardrails
- Both checkpoints need a human. Headless runs stop at each and write what a human would have seen.
- One writer per file across all builders.
- Never write `do_not_touch` paths. Never push, deploy, or merge to main.
- Never ask for, print, or log a secret's value.
- Fix rounds cap at 3; escalations go to `.harness/state.md`.
