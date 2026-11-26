### Added

- Gap research: a mode of `/dt:loop` that looks for gaps, missed items and useful features in the end state and records each as a suggestion with `scripts/gap_research.py`. It runs before the roadmap is locked and at checkpoints, including `/dt:learn`. Applying a suggestion edits the end state, so the roadmap needs a new lock. Suggestions that need a paid service, account or API key are escalated to the owner as Decisions items and are never applied by an agent.
