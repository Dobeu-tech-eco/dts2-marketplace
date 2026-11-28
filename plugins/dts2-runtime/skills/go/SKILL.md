---
name: go
description: Pick and run the next harness command from the repo's state, then repeat until a person is needed. A script chooses the route. Use when the user says go, what next, which command do I use, or take this repo forward. `status` shows the ladder; `stop` sets the stop file.
---

# Go: the next command, chosen from repo state

One entry point. `next_step.py` reads the repo and returns one rung of a fixed ladder. You run the command it names, then ask it again. You never choose the route yourself, and you never skip a rung because it looks unnecessary.

## The ladder

The first rung that applies wins.

| Rung | State | Next command |
|---|---|---|
| 0 | `stopped` (`.harness/STOP` exists) | none: a person deletes the file |
| 1 | `no-composio-decision` | `/dt:composio` (the user types it) |
| 2 | `no-end-state` | `/dt:setup` |
| 3 | `end-state-not-approved` | `/dt:setup` to revise and approve |
| 4 | `roadmap-not-approved` | none: the owner says "lock it in" in chat, or runs `approvals.py lock-roadmap` in their own terminal; an agent may run `approvals.py lock-roadmap <key>` with the current key |
| 5 | `sections-outstanding` | `/dt:dpp` when two or more sections are `todo`, else `/dt:run` |
| 6 | `open-pull-requests` | `/dt:pr-sweep` |
| 7 | `action-items-open` | `/dt:action-items` |
| 8 | `deploy-planned` | `/dt:run` for the planned deploy |
| 9 | `acceptance-outstanding` | `/dt:run` for the unmet acceptance criteria |
| 10 | `complete` | `/dt:learn` |

## Steps

1. **Count open pull requests** when `gh` is signed in: `gh pr list --state open --json number --jq length`. If `gh` is missing or fails, leave the count out; rung 6 is then skipped and you say so once.
2. **Ask for the next step.** `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/next_step.py" --repo . [--open-prs <n>] next`. It prints one JSON object: `rung`, `state`, `next_command`, `reason`, `blocked_on`.
3. **Act on it.**
   - `blocked_on` is set: print `Stopped at rung <rung> (<state>): <blocked_on>` and stop. Do not look for another way forward.
   - `next_command` is `composio`: that skill starts only when the user types it. Print `Next: type /dt:composio. <reason>` and stop.
   - Otherwise print `Next: /dt:<next_command>. <reason>` and run that skill now. Its own checkpoints and gates apply unchanged.
4. **Repeat from step 1** when the command finishes. Stop when the script returns the same rung twice in a row, and report that rung as stalled with what the command left undone.

## Roadmap approval (rung 4)

The roadmap is the end state's sections and acceptance criteria. Its scope key changes when a section or criterion is added, removed or renamed, and stays the same when work is completed.

1. Write the view: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/roadmap.py" --repo . build`. Show `.harness/roadmap.md` to the owner.
   Before the lock, a gap research pass can add suggestions to the end state (`loop` section 6). Applying one changes the key, so lock after it.
2. Show the `blocked_on` text. In Claude Code the owner locks it in chat in their own words ("lock it in", "approved, lock the roadmap") or with `lock roadmap <key>`. In any other harness (Codex, T3 Code, Cursor) the owner runs `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/approvals.py" lock-roadmap` in their own terminal and types yes; the prompt times out after 120 s.
   An agent may lock it itself with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/approvals.py" lock-roadmap <key>`, passing the key from `blocked_on`, when the roadmap has a scope and is not locked yet. A stale or missing key locks nothing, and the log records the lock as `agent:<name>`. With no terminal attached (`codex exec`, Gemini, WSL, native Windows agent runs) it never prompts: it locks only on two providers' recorded sign-offs for that key, logged as `agent:undetected`.
3. Stop, unless you locked it with the current key in step 2. Otherwise a hook records the lock, and only from the owner's own typed message: a question, a negation or a condition is never a lock, and neither is a plain yes. Never write `.claude/settings.local.json` yourself, and run `lock-roadmap` only with the current key.
4. No hook runs in the instruction edition from the Claude plugin directory. There the owner adds the key to `dts2_approvals.roadmap` in `.claude/settings.local.json` by hand. Tell them the exact entry, and still never write the file yourself.

A changed scope needs a new approval. Say so when rung 4 returns after the roadmap was approved before.

## Other forms

- `/dt:go status`: run `next_step.py --repo . [--open-prs <n>] status` and show the ladder as printed. The current rung is marked `>`. Read-only.
- `/dt:go stop <reason>`: run `next_step.py --repo . stop --reason "<reason>"`. Every later `/dt:go` returns rung 0 until a person deletes `.harness/STOP`. The loop guard for `fullauto` reads the same file. Never delete it yourself.

## Any seat can start it

The router is a plain script with no model call, so every seat on the roster gets the same answer from the same repo. A seat that is not Claude (a Codex, Grok or other provider session) starts the ladder by running `next_step.py --repo . next` itself and following the steps above with its own way of running a harness command.

Starting the ladder gives a seat no extra authority. The owner's approvals, the hard gates and the stop file apply to every seat alike. When a rung goes to a council, the Claude seat is head of council and breaks a split, as in `autopilot`.

## Rules

- The script reads files only. It makes no network call and changes nothing except in `stop`.
- Roadmap approval covers the plan. It does not approve a merge to a protected branch or a deploy. Those keep their own approval, and the merge guard and policy gate still decide.
- Tests, checks, the secret scan and `do_not_touch` stay hard gates. No rung, vote or council overrides one.
- If the script fails or prints something that is not the JSON above, report the output and stop. Do not guess the rung.
