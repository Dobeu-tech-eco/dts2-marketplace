---
name: run
description: Run the dts2 plan-build-review-verify pipeline on a task, automatically sizing the team (1 to 6 parallel builders, 1 to 4 parallel reviewers, git worktrees for large jobs) from the repo and task size, across one repo or a multi-repo workspace. Two human approval gates. Use when the user asks to run the harness, harness a task, or do a multi-file, cross-package, or cross-repo change with rigor.
---

# Run — auto-scaled pipeline

## Preflight
1. Find config: `.harness/config.yaml` in the repo, or `.harness-workspace.yaml` in a parent folder. If neither exists, stop and point to the `setup` skill.
2. Read `.claude/dts2-harness.local.md` for `auto_scale`, `max_builders`, `max_reviewers`, `use_worktrees`. Defaults: true, 6, 4, auto.
3. `git status --porcelain` in every repo involved. If dirty, ask: stash and restore after, build on top, or abort.
4. If the task is under 10 words or vague, ask one clarifying question.
5. Production deploys, data deletion, auth, or payments → confirm before anything else.

## Phase 0 — Size (scout)
Dispatch `dts2-harness:scout` with the repo path(s) and the task. Use its tier unless `auto_scale` is false (then tier S).

## Phase 1 — Plan (lead)
Dispatch `dts2-harness:lead` with the task, config, lessons, scout report, and workspace manifest if present. For a workspace, lanes are per repo; contract owners come before consumers.

**Gate 1:** show the plan, lane count, and team (builders, reviewer axes, worktrees). Approve, edit, or abort. Silence means abort.

## Phase 2 — Build (parallel builders)
- Builders = min(lanes, tier builders, `max_builders`).
- Worktrees when the tier says so or `use_worktrees: always`: for each lane run `git worktree add ../<repo>-dts2-<lane> -b dts2/<lane>` and give that builder only its worktree. Never when `use_worktrees: never`.
- Dispatch every independent lane's `dts2-harness:builder` in one message so they run at once. Dependent lanes start only after their dependencies report done.
- A builder that asks for a file outside its lane: pause that lane, ask the user.
- A lane failing 3 times on the same error: stop it and report. Do not retry blindly.
- With worktrees, merge each lane branch back into the working branch in plan order once its lane is done. A merge conflict stops the run and goes to the user.
- Run the integration task, if any, last.
- Show `git diff --stat` per repo.

## Phase 3 — Review and verify (parallel)
In one message dispatch:
- One `dts2-harness:reviewer` per axis from the tier (S uses one reviewer on all axes), capped at `max_reviewers`.
- One `dts2-harness:verifier` per repo touched.
If `second_opinion` is `codex` or `gemini` and that CLI is installed, also run `codex exec "<review prompt + diff>"` or `gemini -p "<review prompt + diff>"` through Bash and include its findings marked as advisory.

## Phase 4 — Decide
Merge findings, dedupe by file:line, keep the highest severity.

**Gate 2:** verifier verdicts, findings by severity, lesson candidates. Options: ship, fix CRITICAL/HIGH and re-check, or abort and revert.
- Fix: send only the blocking findings to the builders that own those files, then rerun Phase 3. Cap at 3 rounds. After 3, stop and say the plan is likely wrong.
- Ship: propose a commit message per repo. Commit only on an explicit yes. Never push.
- Abort: revert the harness's changes the way the user picks, remove dts2 worktrees, restore any stash.

Append the reviewers' lesson candidates to `.harness/lessons-inbox.md` in each repo, then mention the `learn` skill.

## Status lines
```
Size   — tier M, 2 builders, reviewers: correctness, security
Plan   — 3 lanes + integration, waiting for approval
Build  — lane A done, lane B 2/3
Check  — verifier VERIFIED, 1 HIGH finding
```

## Guardrails
- Never skip either gate, even in auto mode.
- One writer per file across all builders.
- Never write `do_not_touch` paths. Never push, deploy, or merge to main.
- Verifier BLOCKED means not done, unless the user explicitly overrides and the reason goes in the commit message.
