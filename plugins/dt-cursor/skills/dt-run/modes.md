> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# run — modes and status lines

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

## review-pr mode
`run review-pr <number>` reviews an existing pull request (Rule 10.6).
1. Run the Preflight steps that apply (config, ignore guard, roster, clean tree), then `gh pr checkout <number>`. Record the base branch from `gh pr view <number> --json baseRefName`.
2. Run only Phase 3 (walkthrough, reviewers, final review), Phase 3b, Phase 3c and the verifier, on the PR diff against its base. No plan, no builders, no commits.
3. If checking out or rebasing the PR hits a merge conflict, install and run `/resolve-merge-conflicts` before touching it by hand; if it cannot resolve cleanly, stop and hand it to the user. Show the findings by severity and the verifier verdict. Post them as a PR comment (`gh pr comment <number> --body-file <findings file>`) only on an explicit yes.
4. Never build, commit or push on a PR this run did not open.
