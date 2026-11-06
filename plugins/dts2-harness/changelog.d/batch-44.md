### Added

- `/dts2:pr-sweep [owner/repo] [--stale-days N] [--mine|--author A|--head-prefix P] [--optimise-ci]`: clears open and stale PRs in one pass with parallel workers. It buckets every PR (green, needs rebase, CI red, stacked, superseded, stale, draft, needs you), merges green PRs with merge commits, closes dead ones with a linking comment, triages red CI (fix, retry once, ignore non-required, flaky, escalate) and reports what waits on the user. `--optimise-ci` adds a separate CI-speed PR; `--run <stamp>` limits it to one autopilot run's PRs.
- `scripts/pr_sweep.py`: `inventory` (REST-only `gh api`), `classify`, `order`, `record` and `report` for the sweep, all printing JSON.
