# Phase 2 — CI triage

## Required checks
Read them from branch protection per base branch: `gh api repos/<o>/<r>/branches/<base>/protection`, then `required_status_checks.contexts` and `required_status_checks.checks[].context`. `inventory` already does this and stores them in `inventory.json`. If protection is unreadable (403 or 404), treat every check as required.

## Per red PR
For each failing or cancelled check pull the log (`gh run view <id> -R <o>/<r> --log-failed`) and decide one verdict:

| Verdict | When | Action |
|---|---|---|
| FIX | the PR caused it (test, lint, type, version-count, changelog contract) | a sonnet worker fixes it in the PR's worktree with a new commit. It runs the repo's fast checks locally first (the test command from `.harness/commands`, or the repo's documented one; the repo's pinned ruff; shellcheck), pushes the PR branch, and re-watches CI. Cap 3 rounds per PR, then bucket H. |
| RETRY ONCE | infra noise (runner timeout, network, rate limit); quote the log line as evidence | `gh run rerun <id> -R <o>/<r> --failed` once. Red again: FIX or H. |
| IGNORE | the check is not required by branch protection and is known-unrelated (for example a preview deploy cancelled for an unsigned commit) | comment on the PR with the log line. Never mark a required check ignorable. |
| FLAKY | the same test passes on the base branch and on a re-run with no code change | do not delete or skip it. Append to `.harness/pr-sweep/<stamp>/flaky.md`: test, PR, both run links. It feeds `phase-4-optimise-ci.md`. |
| ESCALATE | looks like a real bug on the base branch, or the fix needs a hard-stop action | bucket H, with the log line and the decision needed. |

## Rules
- Never skip a test. Never weaken, delete or loosen a valid test or a lint rule to get green.
- Record each verdict: `pr_sweep.py record --dir <dir> --pr N --bucket C --action <fix|retry|ignore|flaky|escalate> --ci <fixed|retried|ignored|flaky|escalated> --reason "<log line>" --worker <model>`.
- Ledger lines are the only source of the report; record as you go.
