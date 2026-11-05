### Fixed

- D74 (son sandbox): the son guard no longer reads an interpreter's script argument inside the plugin's own `scripts/` as a write target, so `python3 -I ~/.claude/plugins/.../lanes.py` runs in a son; `lane_env` sets `CLAUDE_PLUGIN_ROOT` and keeps pnpm's store, operation lock and state dir in the sandbox-writable run cache. Every son in a 3.11.0 autopilot run had parked before building.
- H-004 (context guard): an approved plan counts as the plan checkpoint even when the run saved no `plan.md`: `plan.out.json`, `lanes.json`, or a `plan approved` line in the run's `state.md` (now written on approve).
- H-003 (handoff): `handoff-write.py --checkpoint/--clear-checkpoint` records a pending plan or ship checkpoint in `.harness/state.md`, and the handoff's Next action names it before the first open action item.
- H-006 (builders): `companion-gate.py check` reports `installed`; builders run `/improve-codebase-architecture` only when installed and never `npx skills add` inside their checkout.
