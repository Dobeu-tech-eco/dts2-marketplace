---
name: run
description: Run the dts2 plan-build-review-verify pipeline on a task in one repo or a multi-repo workspace. Sizes the team from the repo and task, checks which agents are available and what they cost, plans against the approved end state, builds with parallel builders on separate file sets, reviews and walks the changed screens, and ends with a receipt. Two human checkpoints (plan, ship). Also `run add secret NAME` to close a deferred secret. Use when the user asks to run the harness, harness a task, or do a multi-file, cross-package, or cross-repo change with rigor.
---

# Run — plan, build, review, verify, ship

Follow the phases in order. Every agent dispatch uses the Agent tool with `subagent_type: dts2-harness:<role>` and a `model` override taken from `roster.py model` (claude: `economy` → `haiku`, `standard` → `sonnet`, `frontier` → `opus`). The lead and the verifier always run on `frontier`.

If the request is `run add secret NAME`, skip to **Add secret mode**.

## Preflight

**Resume mode.** If the request is `run resume`, read `.harness/handoff/latest.md` first (if it is missing, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" <repo>` to build it). Print its `## State`, `## Open items` and `## Next action`, then ask once: `Continue with the next action? (y/n)`. On yes: if the next action is a `run add secret NAME` command, go to **Add secret mode**; if it says the latest receipt is not approved, show that receipt and resume at the **Ship checkpoint**; if it says there are no open items, ask `What is the next task?`; otherwise run the pipeline below with the next action as the task. On no, stop. Open action items can be listed or changed with `/dts2-harness:action-items`.
0. **Scope.** Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" .`. `workspace-member` → say exactly `Pivot: <repo> belongs to workspace <root>; running in workspace mode from <root>.` and use the workspace root for every later path; `none` → run `/dts2-harness:setup` first; otherwise continue. If `.harness/keep.yaml` exists at the effective root, read it: for each skill listed with source `npx skills add <ref>` that is not on disk (`.claude/skills/<name>`, `~/.claude/skills/<name>`), add its install command to `.harness/action-items.md` → `## Decisions` as an action item instead of failing.
1. **Harness change.** If the request names a harness skill, agent, hook, or profile (a dts2-harness file, not the repo's own code), print `That changes the harness itself; use `/dts2-harness:evolve`.` and stop. Never plan a harness change as a repo task.
2. **Config and mode.** Look for `.harness/config.yaml` in the repo, then `.harness-workspace.yaml` in a parent folder. Neither → stop and point to `/dts2-harness:setup`. Print one mode line: `Mode: workspace` if `.harness-workspace.yaml` was found, else `Mode: single`.
3. **Ignore guard.** For each repo involved: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-ignored.py" <repo>`.
4. **End state.** If `.harness/config.yaml` exists and `.harness/end-state.md` does not, print exactly `No end state yet; /dts2-harness:setup interviews to one.` and continue.
   **Planned deploy.** If `.harness/end-state.md` has `deploy.status: planned`, say `Production target is planned but not built yet; building it first.` and run this pipeline on the task `Build the production target: <deploy.plan>` (both checkpoints apply). Then ask once: `Continue with your task now? (y/n)`
5. **Settings.** Read `.claude/dts2-harness.local.md`: `auto_scale` (default true), `max_builders` (6), `max_reviewers` (4), `second_opinion` (none), `auto_learn` (true), `continuous_dispatch` (true), `builder_timeout_min` (20).
6. **Roster.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" resolve --config .harness/config.yaml`. On error, show it and stop. Keep the JSON.
7. **Clean tree.** `git status --porcelain` in every repo involved. If dirty, ask once: stash and restore after, build on top, or stop. Record `git rev-parse HEAD` per repo as the rollback point.
   **Run branch.** In each git repo, take the run stamp (`date +%Y%m%d-%H%M%S`), create `dts2/<stamp>` from the current branch with `git switch -c dts2/<stamp>`, and record the stamp and branch in `.harness/runs/<stamp>/state.md`. Reuse that stamp for the rest of the run. Non-git folders have no run branch.
8. If the task is under 10 words or vague, ask one clarifying question.
9. Production deploys, data deletion, auth, or payments → confirm before anything else.

## Phase 0 — Size and Budget check
1. Dispatch `dts2-harness:scout` (`model: haiku`) with the repo path(s) and the task. Use its tier unless `auto_scale` is false (then tier S).
2. **Budget check** (`roster.py probe`). Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" probe --config .harness/config.yaml`. From its JSON:
   - Drop every agent in `dropped` for this run; keep its `reason`.
   - An agent with budget `low` keeps only the `second-opinion` role (the probe already restricts its `roles`); never give it a builder or reviewer seat.
   - Keep the probe JSON for the lead. Each agent carries `costTier` (1 cheapest).
   - Auth: each probe entry carries `auth` (`subscription`, `api-key`, `installed (unverified)` or `none`). Agents already logged in via subscription are used as-is; never prompt for a second authentication or an API key. An agent is dispatched via API key only when its roster entry says `auth: api-key` and `included: true`.
   - Claude is always usable for this run (it is running this skill); if the probe drops `claude`, keep it and show the reason as a one-line warning.
3. Resolve models once per agent you may use: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" model --agent <name> --tier <economy|standard|frontier>`. `null` means use that agent's default model.

## Phase 1 — Plan (lead)
Dispatch `dts2-harness:lead` with `model` = claude `frontier` (`opus`). Give it: the task verbatim, `.harness/config.yaml`, `.harness/end-state.md`, `.harness/discipline.md`, `.harness/lessons.md`, the scout report, the roster JSON, the probe JSON, and the workspace manifest if present. Tell it:
- Assign only agents in the probe's `usable` list, by `costTier`: the cheapest available agent whose roles include the seat for builders rated `complexity: mechanical` and for axis reviews; the strongest for the plan, the verifier, and the final review.
- Rate every `### Builder N` with `complexity: mechanical|normal|design`.
- Plan from the `## Sections` table and end the plan with `## Ready queue` for sections that are ready but beyond the builder cap.

**Plan checkpoint.** It will not open without the lead's `## Done` section with at least one line. If the section is missing or empty, send the plan back to the lead once with "Add the Done section: one outcome per line with its check method." Still missing → stop and say why.

Show, in this order:
- The plan as the lead wrote it, including `## Done` and `Axes:`.
- `Team: N builders on separate file sets`, reviewer axes, and one line per seat: `<role> — <agent> (<tier>, <auth>)`, where auth is `subscription`, `api-key`, `installed (unverified)`, or `handoff` for IDE agents, for example `builder 2 — codex (standard, api-key)`.
- One line per dropped agent: `Dropped: <agent> — <reason>`.
- The output of `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/metrics.py" <repo> trend` as one line (`Trend: no runs yet` on a first run).
- When `## Sections` exists, the whole batch in one line: `Sections this run: <n> of <total> (ready now: <k>, queued: <q>, blocked: <b>)`.

**Blueprint check.** If `.harness/end-state.md` has a `## Blueprint` block, the plan must carry a `## Blueprint coverage` section mapping every layer to `Builder N` or `unchanged`. A layer with no mapping blocks the checkpoint: send the plan back to the lead once with `Blueprint layer <x> unmapped`. Still unmapped → stop and say why.

Then say exactly: "Here is the plan, the done-criteria, and who does what. Approve, edit, or stop." Silence means stop. On edit, revise with the lead and show the checkpoint again. Any choice the user defers here goes to `.harness/action-items.md` → `## Decisions` as `| <item> | <context> | open | | <YYYY-MM-DD> |` (create the file from `${CLAUDE_PLUGIN_ROOT}/templates/action-items.md` if absent).

## Phase 2 — Build (parallel builders)
1. Builders = min(builder sections in the plan, scout's builder count, `max_builders`). Each builder works on its own file set in the isolation that **Isolation (Rule 10)** below sets.
2. Every dispatch names a model (Rule 9.2). Model per builder from its `complexity`: `mechanical` → `economy`, `normal` → `standard`, `design` → `frontier`. A Claude builder is an Agent dispatch with that `model`. A live non-Claude builder runs through Bash as the argv from `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roster.py" command --agent <name> --role builder --tier <tier>`, with `{prompt}` replaced by the brief and `{addDir}` (gemini) by a folder holding the brief and diff as files, run from the target repo; that argv already carries the resolved model and the permission flags the profile needs (grok builders: edits allowed, no shell). Follow the `notes` it returns.
3. Dispatch every independent builder in one message so they run at once. Dependent builders start only after their dependencies report done.
4. **Handoff agents** (in the roster's `handoff` list): write `.harness/handoff/<agent>/<n>.md` (the builder's tasks, files, done-when) and the agent's rules file from its profile `rulesFile`, then pause that builder until the user says done. Record it with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/action-items.py" <repo> add Handoff ".harness/handoff/<agent>/<n>.md builder <n>"` and `… assign <id> <agent>`; mark it `done` when the user reports done.
5. A builder that asks for a file outside its file set: pause that builder and ask the user.
6. A builder that reports `SECRET NEEDED`: handle it as in **Secrets** below; the others keep going.
7. A builder failing on the same error: rounds 1–2 resume the same builder; round 3 goes to a fresh builder one tier up (`economy→standard→frontier`); after round 3 stop it, escalate with what failed, and record it in `.harness/state.md` under `## Failures and escalations`. Three materially identical failures mean change the approach, not retry blindly.
8. Run the integration task, if any, last. Show `git diff --stat` per repo.

### Secrets
A secret's value never passes through the chat, a prompt, or an agent's context. On a builder's `SECRET NEEDED: NAME — <what it unlocks> — <where consumed>` line, pause that builder only and ask once: **provide now** or **add later**.
- **provide now**: name the variable and exactly one place to put it: a `NAME=` line in `.env`, the project's secret manager command, or `gh secret set NAME` for CI. Wait for the user to say "done". Check presence only, never print a value: for `.env` or the environment, `test -n "${NAME:-}"` or `grep -qE '^NAME=.+' .env`; for GitHub Actions (`gh secret set NAME`), `gh secret list | grep -qE '^NAME\b'` (key names only). Present → resume the builder. Missing → say so and ask again once.
- **add later**: append `| NAME | <what it unlocks> | <where consumed> | <how to add> | open | | <YYYY-MM-DD> |` to `.harness/action-items.md` → `## Secrets` (create from the template if absent); add `NAME=` with a one-line comment to `.env.example`; let the builder keep its not-configured path. If any wiring was left undone because the secret is missing, write the status as `open, deferred wiring` and say what was deferred in `consumed in`.

The run continues either way. Open secrets appear in the receipt under *Steps outside this change*, and they never block the commit or the PR.

## Continuous dispatch (never idle)
Setting: `continuous_dispatch: true` (default) and `builder_timeout_min: 20` in `.claude/dts2-harness.local.md`. With `false`, Phase 2 dispatches the plan once and waits, as before.

Keep `max_builders` (from the tier) builders in flight at all times while the lead's `## Ready queue` is non-empty. On any builder event (finished, reported BLOCKED or NEEDS_CONTEXT, `SECRET NEEDED`, no report within `builder_timeout_min`, or entering fix round 3) do two things in one step:
- (a) **Handle that builder.** VERIFIED-ready: merge its branch. Stalled: park its section as `blocked` with an action item (Secrets, Decisions or Handoff), write the id into the section cell in `end-state.md` (for example `payments webhook (S2)`), and clean up its builder checkout as **Isolation (Rule 10)** says. If the fix-round cap is hit, escalate per Rule 8.
- (b) **Dispatch the next ready section(s)** from the queue to fresh builders in the same message. Re-check that each file set does not overlap any in-flight builder; on a conflict skip to the next ready section. If every ready section conflicts, wait for the next event instead of dispatching.

Stuck-but-not-stopped: a parked section never halts the run. The run ends only when the queue is empty and no builder is in flight, at a checkpoint, or on a hard stop or context guard.

Partial ship: at the ship checkpoint, verified sections ship; parked sections are listed in the receipt under `Steps outside this change` with their action-item ids, and the section statuses in `end-state.md` are updated (`done`, `blocked` or `todo`).

## Phase 3 — Review and verify
Use the run stamp taken in preflight. Pass it to every reviewer and verifier.
1. **Verifier walkthrough first**, when `Axes:` include `walkthrough`: dispatch `dts2-harness:verifier` (`model: opus`, one per repo touched) with the plan, the stamp, and the repo. Wait for its table; the reviewers need its screenshots and FAIL rows. Without the walkthrough axis, dispatch the verifier together with the reviewers in step 3.
2. **Critique report**, when `Axes:` include `critique`: if `/impeccable` is available, run `/impeccable critique` on the changed screens and save its report to `.harness/review/critique-<stamp>.md`. Otherwise the critique reviewer writes it, and you save its `### Critique` section to that same path.
3. Then dispatch the reviewers in parallel, in one message: one `dts2-harness:reviewer` per axis (tier S: one reviewer on all axes), capped at `max_reviewers`, each on its assigned agent at `standard`. Give each the diff, the plan, the stamp, and the critique report path when there is one. For `walkthrough-findings`, include the verifier's table.
4. Second opinion: for each usable agent holding `second-opinion` (or the `second_opinion` setting when it names an installed CLI), run the argv from `roster.py command --agent <name> --role second-opinion --tier standard` with `{prompt}` replaced by the review prompt and the diff, through Bash. Mark its findings advisory.
5. **Final review.** After the axis reviews return, dispatch one `dts2-harness:reviewer` on the whole diff, all axes, at `frontier`, with the axis findings, to catch what crosses axes.

## Phase 3b — Finish pass
Runs only when `/impeccable` is available and the diff touched UI components named in `.harness/end-state.md`. If the diff touched such components and Impeccable is not installed, print one line, `Finish pass skipped: Impeccable not installed (github.com/pbakaus/impeccable)`, and go to Phase 4.

The builder that owns the files runs, inside its file set, in one dispatch:
- `/impeccable polish <components>` always (it consumes the critique's Fix list);
- `/impeccable harden <components>` when the diff touches data loading, network, or error paths;
- `/impeccable clarify <components>` when it touches error, empty, or confirmation states;
- `/impeccable optimize <components>` only when the walkthrough marked a screen slow.

One round, no loop. Then go to Phase 3c; its verifier run covers this result.

## Phase 3c — Code finish pass
Runs on every code diff, after Phase 3b (or straight after Phase 3 when 3b was skipped) and before the final verifier tests. Two extra reviewer axes on the diff, dispatched as one `dts2-harness:reviewer` at `standard`:
- `simplify`: duplication, dead code, functions over about 20 lines, unclear names, speculative abstraction.
- `optimize`: only for files the walkthrough marked slow or a test marked slow; never speculative. No slow marker → report `optimize: n/a`.

The builder that owns the files applies the resulting fix list inside its file set, once. Then dispatch the verifier (`model: opus`) to run the configured tests on the result; its table replaces the earlier test rows and adds a `Coverage:` line for changed source files with no test that imports or exercises them. This pass counts toward the 3-round cap in Phase 4: it is one of the rounds, not an extra one.

## Phase 4 — Ship checkpoint
1. Merge findings, dedupe by file:line, keep the highest severity.
2. Build the receipt from `${CLAUDE_PLUGIN_ROOT}/templates/receipt.md` and save it to `.harness/runs/<stamp>/receipt.md`: tests run with pass/fail/skip counts from the verifier, review verdict, approver (left as the template placeholder until ship), steps outside this change (open secrets and decisions from `.harness/action-items.md`, handoff work), open risks, rollback point (the SHA recorded in preflight).
3. Show the receipt, findings by severity, the verifier verdict, and lesson candidates. Then say exactly: "Here is the receipt. Ship, fix the blocking items and re-check, or stop and revert."
- **Fix**: send only the CRITICAL and HIGH findings to the builders that own those files, then rerun Phase 3. Cap at 3 rounds. After 3, stop and escalate with what failed; record it in `.harness/state.md`. Rounds 1–2 resume the same builder; round 3 goes to a fresh builder one tier up (`economy→standard→frontier`).
- **Ship**: fill the receipt's `### Approved by` line with `$(git config user.name), $(date +%Y-%m-%d)` (ISO date), replacing the template placeholder; never create a PR from a receipt that still has it. Then do **After ship** below, then propose one commit message per repo and commit only on an explicit yes. Never push. When the user pushes and asks for a PR, create it with `gh pr create --body-file .harness/runs/<stamp>/receipt.md`; open secrets do not block it.
- **Stop and revert**: revert the run's changes the way the user picks, restore any stash, and clean up the run's builder checkouts as **Isolation (Rule 10)** says.

Verifier BLOCKED means not done, unless the user explicitly overrides; the reason then goes in the commit message and `.harness/state.md`.

## After ship
Do these before the commit so they land in it. Do not narrate the writes.
1. Append the reviewers' lesson candidates to `.harness/lessons-inbox.md`. If `auto_learn` is not `false`, run the `learn` skill in its auto mode on those candidates and put the resulting `lessons.md` diff in the ship summary; no separate approval prompt. If `auto_learn` is `false`, still run only learn's **Run metrics** step so the Trend line stays current.
2. In `.harness/end-state.md`, check the acceptance boxes the plan covered and the verifier confirmed, and update each touched component's status.
3. Append the ship decision to `.harness/state.md` → `## Decisions` as `- <date> <what shipped, receipt path>`.
4. **Write handoff.** Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" <repo>` last, after the other writes, so `.harness/handoff/latest.md` reflects them. It never contains a secret's value.
5. Include `lessons.md`, `.harness/metrics.jsonl`, `.harness/harness-lessons.md` (if changed), `end-state.md`, `state.md`, `action-items.md` (if changed), and `.harness/review/critique-<stamp>.md` (if written) in the commit. `handoff/latest.md` is regenerated, not committed.

## Deployment verification
Runs only when `deploy.provider != none` in `.harness/end-state.md`. Read `deploy.provider`, `deploy.productionUrl`, `deploy.checkCommand` and `deploy.status`. The harness never deploys, pushes, or re-runs CI except on an explicit yes inside the troubleshoot round below. It never creates provider accounts or enters credentials; secrets are presence-only.

If the `deploy:` block is missing or `provider: unset` (v2 or `--scaffold-only` repos), after the PR is opened run `deploy-detect.py` and ask the setup skill's deploy question once, record the answer in `end-state.md`, then continue.

**Planned deploy.** Started from Preflight step 4. When `deploy.status` is `planned`, build `deploy.plan` as its own run, before any feature run: the provider config file, a deploy workflow, secret names to `## Secrets` (never values) and DNS, domain and account steps to `## Deploy` in `.harness/action-items.md`, via `action-items.py <repo> add`. On the first passing deploy, set `deploy.status` to `live` and run the production walkthrough below.

**Watch.** After the PR is opened, print: `Deploy watch: <provider> — run `<checkCommand>` or tell me when it is live`; when `checkCommand` is null, print `Deploy watch: <provider> — tell me when it is live`. Wait for the user to confirm, or for the check output they paste to show the new commit deployed. Never run the deploy yourself.

**Production walkthrough.** Once confirmed, dispatch `dts2-harness:verifier` (`model: opus`) with `Mode: production`, `URL: <productionUrl>`, the plan's `Done` screens and the run stamp. It repeats the walkthrough screens against the URL, saves `prod-<screen>.png`, and returns PASS or FAIL per screen. Replace the line under the receipt's `### Production` heading with `- Production: <url> | <deploy id or commit> | walkthrough PASS n/n | <ISO time>`, then update the open PR with `gh pr edit <n> --body-file .harness/runs/<stamp>/receipt.md`.

**Failure.** A FAIL in the deploy check, CI, or the walkthrough → ask exactly: "Production/CI failed at <step>. Investigate and troubleshoot?"
- **No**: record an open item in the receipt (`Production:` line and Open risks) and in `.harness/state.md`, and end the run.
- **Yes**: troubleshoot round. Gather evidence (`gh run view <id> --log-failed`, provider logs, the walkthrough's console and network errors), state the root cause, propose a fix, then present these options, each needing its own explicit yes:
  - (a) follow-up PR (default)
  - (b) `gh run rerun <id>`
  - (c) redeploy or push to production with the provider command from `DEPLOY_COMMANDS` in `deploy-detect.py`: vercel `vercel --prod`, cloudflare `wrangler deploy`, netlify `netlify deploy --prod`, fly `fly deploy`, github-workflow `gh workflow run <file>`
  - (d) roll back to the receipt's rollback point

The troubleshoot round counts toward the 3-round cap. Without that explicit yes the harness never deploys, pushes, or re-runs CI.

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

## Isolation (Rule 10)
Setting: `use_worktrees` in `.claude/dts2-harness.local.md` (`auto` default, `always`, `never`).
- **Git repo, `auto` or `always`:** one worktree per builder. For builder `<n>` run `git worktree add ../<repo>-dts2-<n> -b dts2/<stamp>/b<n> dts2/<stamp>` and give that builder only its worktree. `never` is the explicit opt-out: builders share the run branch's tree on separate file sets.
- **Not a git repo:** one scratch directory per builder, `.harness/wt/<n>/`, with a disjoint owned-file list. The lead copies results into the canonical location and keeps a diff summary in `.harness/runs/<stamp>/`.
- **Workspace:** builders are grouped per repo; contract owners build before consumers, following the manifest's `release_order`. `always` forces worktrees in workspace mode too. Handoff lanes use `.harness/handoff/<agent>/<n>.md` inside the owning repo.
- **Merge, after green:** when the verifier reports VERIFIED, the lead merges each builder branch into `dts2/<stamp>` in plan order, re-runs the full test suite and every configured check after each merge, and resolves conflicts itself. Then it removes each builder worktree (`git worktree remove`) and deletes its branch. A conflict the lead cannot resolve stops the run and goes to the user.
- **Stop and revert** removes the run's worktrees and branches after reverting. Never push, never merge to the default branch.

## review-pr mode
`run review-pr <number>` reviews an existing pull request (Rule 10.6).
1. Run the Preflight steps that apply (config, ignore guard, roster, clean tree), then `gh pr checkout <number>`. Record the base branch from `gh pr view <number> --json baseRefName`.
2. Run only Phase 3 (walkthrough, reviewers, final review), Phase 3b, Phase 3c and the verifier, on the PR diff against its base. No plan, no builders, no commits.
3. Show the findings by severity and the verifier verdict. Post them as a PR comment (`gh pr comment <number> --body-file <findings file>`) only on an explicit yes.
4. Never build, commit or push on a PR this run did not open.

## Context guard and pivot
When a `dts2-harness CONTEXT GUARD` message arrives (from the hook), or the lead itself notices it has made more than ~250 tool calls without reaching the plan checkpoint, say exactly one line first: `Context guard fired (<trigger>): stopping all agents and re-running setup.` Then:
1. Stop. No new dispatches; tell running builders to stop and discard their partial work (worktrees are removed, nothing is merged).
2. Write an escalation to `.harness/state.md` → `## Failures and escalations` as `- <date> context guard: <trigger> — <details>` and refresh the handoff file with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" <repo>`.
3. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" .`.
4. If scope is `workspace-member` or `none`, or no end state exists, invoke `/dts2-harness:setup`; it re-links an existing workspace manifest without re-interviewing and keeps everything in `.harness/keep.yaml`.
5. Then `run resume`.

## Guardrails
- Context guard: a spike before the plan checkpoint stops the run and re-runs setup; never push through it.
- Both checkpoints need a human. Headless runs stop at each and write what a human would have seen.
- One writer per file across all builders.
- Never idle while a ready, non-conflicting section exists; never dispatch two builders onto overlapping files to avoid idling.
- Never write `do_not_touch` paths. Never push, deploy, or merge to main.
- Never ask for, print, or log a secret's value.
- Fix rounds cap at 3; escalations go to `.harness/state.md`.
- Every dispatch names a model (Rule 9.2).
- Rulings go to state.md as `Ruling: <what> — <why> — <cost if wrong>`.
