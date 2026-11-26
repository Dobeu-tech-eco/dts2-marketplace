### Changed

- An agent launch (a son, or a process under an agent CLI) can now run `approvals.py lock-roadmap <key>` without a prompt when the roadmap has a scope, the key matches the current roadmap and it is not locked yet. The lock is logged as `agent:<name>`. With no key it exits 2 and locks nothing; with a stale key it exits 1.
