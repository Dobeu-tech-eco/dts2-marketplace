### Fixed
- `subagent_report.already_blocked` handles an unwritable marker file with an explicit documented fallback instead of an empty `except OSError`; behaviour is unchanged and covered by `tests/test_closing_a.py`.

### Added
- `docs/INVENTORY.md`: every skill, agent, hook, CLI script and Makefile target, sourced from the plugin files.
