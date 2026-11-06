# Phase 4 — CI optimisation (only with `--optimise-ci`)

Runs after the sweep is done, never with `--run <stamp>`. One separate PR on branch `sweep/ci-optimise`, built by a sonnet worker in its own worktree from the CI logs and `flaky.md` the sweep produced.

## Candidates
- Dependency and tool caching (package manager, linter, shellcheck).
- Path filters so doc-only or changelog-only PRs skip the full test matrix.
- Test sharding or parallel test runs when the suite is the slow step.
- Drop jobs that duplicate another job.
- Concurrency groups that cancel superseded runs on the same branch.
- A flaky-test quarantine list that still runs those tests and reports them. Never silently skip them.

## Constraints
- Keep every required check name stable so branch protection still matches. If a path filter would leave a required check unreported, keep the job and make it exit early instead.
- Do not weaken a test, lint rule or required check.
- Show before/after wall-clock from at least two runs each (`gh run list -R <o>/<r> --workflow <w> --json databaseId,createdAt,updatedAt`), in the PR description.
- Same rule as any PR: merge when green, merge commit, no `--admin`. A change to workflow files that needs a secret, deploy or release step is a hard stop (bucket H).
- Record the PR in the ledger and add a line to `report.md`.
