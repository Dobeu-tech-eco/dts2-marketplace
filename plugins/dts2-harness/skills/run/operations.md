# run — operations

## Isolation (Rule 10)
Setting: `use_worktrees` in `.claude/dts2-harness.local.md` (`auto` default, `always`, `never`).
- **Git repo, `auto` or `always`:** one worktree per builder. For builder `<n>` run `git worktree add ../<repo>-dts2-<n> -b dts2/<stamp>/main-b<n> dts2/<stamp>/main` and give that builder only its worktree. `never` is the explicit opt-out: builders share the run branch's tree on separate file sets.
- **Not a git repo:** one scratch directory per builder, `.harness/wt/<n>/`, with a disjoint owned-file list. The lead copies results into the canonical location and keeps a diff summary in `.harness/runs/<stamp>/`.
- **Workspace:** builders are grouped per repo; contract owners build before consumers, following the manifest's `release_order`. `always` forces worktrees in workspace mode too. Handoff lanes use `.harness/handoff/<agent>/<n>.md` inside the owning repo.
- **Merge, after green:** when the verifier reports VERIFIED, the lead merges each builder branch into `dts2/<stamp>/main` in plan order, re-runs the full test suite and every configured check after each merge, and resolves conflicts itself. Then it removes each builder worktree (`git worktree remove`) and deletes its branch. When a conflict occurs, install and run `/resolve-merge-conflicts` before touching it by hand (the same for any `git merge` or `rebase` the lead performs). If it cannot resolve cleanly, the existing rule applies: stop and hand it to the user. A conflict the lead cannot resolve stops the run and goes to the user. The skill installs with `npx skills add https://github.com/mattpocock/skills --skill <name>` on first use (see Companion skills in `.harness/discipline.md`), record it in `.harness/keep.yaml` → `skills:` as `- name: <name>` / `source: npx skills add https://github.com/mattpocock/skills --skill <name>` / `serves: harness`, invoke by slash name with the Skill tool (or read its SKILL.md inline when headless); if `npx` is unavailable or the install fails, print `Skill <name> not installed (npx unavailable or offline); continuing without it.`, add a Decisions action item with the command, and continue.
- **Stop and revert** removes the run's worktrees and branches after reverting. Never push, never merge to the default branch.

## Lead stall and failover (Rule 8.7)
If the lead hits a usage or token limit, or goes unresponsive on a thread, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" <repo>`, then resume on the provider `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/failover.py" --current <provider> [--exclude <a,b>]` returns (`next_lead`, honoring `lead_provider`), and record the hand-off and the switch in the receipt. If `next_lead` is `None`, stop with the handoff written and tell the user no eligible provider remains.

## Context guard and pivot
When a `dts2-harness CONTEXT GUARD` message arrives (from the hook), or the lead itself notices it has made more than ~250 tool calls without reaching the plan checkpoint, say exactly one line first: `Context guard fired (<trigger>): stopping all agents and re-running setup.` Then:
1. Stop. No new dispatches; tell running builders to stop and discard their partial work (worktrees are removed, nothing is merged).
2. Write an escalation to `.harness/state.md` → `## Failures and escalations` as `- <date> context guard: <trigger> — <details>` and refresh the handoff file with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff-write.py" <repo>`.
3. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scope-check.py" .`.
4. If scope is `workspace-member` or `none`, or no end state exists, invoke `/dts2-harness:setup`; it re-links an existing workspace manifest without re-interviewing and keeps everything in `.harness/keep.yaml`.
5. Then `run resume`.

## Questions from the user

When the user asks a question rather than giving an instruction ("why", "should we", "what's the difference", "is X better"), install and run `/ask-matt` (see Companion skills in `.harness/discipline.md`) with the question and the harness context (end state, current phase) before answering, and base the reply on its answer. If you are still unsure afterwards (the answer is hedged, depends on facts you do not have, or the user says it is not sufficient), install and run `/research` on the question and report the findings with sources before answering. A missing install never blocks: print `Skill <name> not installed (npx unavailable or offline); continuing without it.`, add a Decisions action item with the command, and answer as best you can.
