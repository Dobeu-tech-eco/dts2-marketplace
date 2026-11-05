### Fixed
- state_io: `lock_drop` moves the lock aside and verifies the token before deleting (restoring a successor's lock), and `lock_touch` checks and refreshes through one open file, so a reclaimed holder can no longer free or refresh its successor's lock.
- state_io: `Store.lock` makes one more acquire attempt after a successful reclaim, so reclaiming a stale lock on the last try no longer raises `LockBusy`.
- proc: import no longer fails on platforms without `signal.SIGKILL`.
- miniyaml: `get_float` uses `math.isfinite`.
- chore: removed unused `VERDICT_KEY`, `VERDICTS`, `SEAT_NAME` (council) and `KEY_VALUE` (mdparse); noted two empty `except` blocks; tests use `assertLessEqual` for subset checks.
