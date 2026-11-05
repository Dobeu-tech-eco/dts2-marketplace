### Added
- `tests/test_inventory_complete.py` fails when a `lanes.py` subcommand, skill, agent, registered hook script, script or Makefile target is missing from `docs/INVENTORY.md`, so the inventory cannot drift.
- `docs/INVENTORY.md` gains a "Changed in 3.10.0" section and a "Called by" column for every command.

### Changed
- `docs/INVENTORY.md` lists all 35 `lanes.py` subcommands (the lifecycle, amend and report commands were missing), the `fixer` agent, `plan_graph.py`, `findings.py`, `review_split.py`, `rollback_ref.py` and `env-detect.py`, with exact usage.
- `ARCHITECTURE.md` describes the `scripts/lanes/` package module by module, `state_io.py` as the sole owner of the run directory layout, the plan graph and briefs, the supervisor and lifecycle, and the hook entry points.
