### Added

- `scripts/loop_guard.py`: the guard for an unattended `/dt:fullauto` loop. `check` stops on a `.harness/STOP` file, an open PR labelled `dts2:stop`, or a spent budget (`loop.max_passes`, `loop.max_hours`). `record` appends each pass to a progress ledger and answers `stall` when the progress hash is unchanged for `loop.no_progress_limit` passes (default 3) or the same failure signature repeats three times in a row. `park` and `sweep` keep items that need a person and list those whose blocker (PR, action item or file) is resolved. `notify` opens or updates one GitHub issue titled "dts2: needs you" and always writes `.harness/loop/need-human.md`; a gh failure never stops the loop.
- `templates/loop.md`: the `.claude/loop.md` for `/loop`, one pass per round (check, sweep, pick, do, record; on stall notify and exit).
- `/dt:fullauto` documents the outer loop: the `/goal` condition text and the per-pass order.

### Changed

- `autonomy: unattended` in `.harness/config.yaml` lifts the `max_fullauto_loops` cap (`lanes.py loop`, `model_call.read_budget`, `settings_cache`); loop_guard's no-progress and budget stops replace it. Without it `max_fullauto_loops: 3` behaves exactly as before.
- `templates/config-supervisor.yaml` documents the `loop:` block and the `autonomy` line.
