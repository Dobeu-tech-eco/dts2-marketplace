### Added
- `/dts2:cooldown` skill and `scripts/cooldowns.py`: a per-account list of agents paused after a usage limit, with reset dates read from the error text or given by the user, shared by every session on the machine.
- `hooks/session-cooldowns.sh` (SessionStart): prints which agents are paused and until when, and which came back, at no model cost.

### Changed
- `roster.py probe` skips a cooling agent without running its probe command, and `roster.py classify` records a cooldown on a quota or usage-limit answer and reports `cooldown` and `needsDate`.
- `failover.py` `next_lead` skips cooling agents (new optional `cooling` argument).
