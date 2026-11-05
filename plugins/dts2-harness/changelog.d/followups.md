### Fixed
- Compact resume pointer picks only stamped run directories and names `.harness/handoff/latest.md` as the handoff file.
- The learn skill prunes stale lessons only after the user approves the proposed drops.
- Run report wall-clock shows `-` for a lane with no `started` instead of the run-wide start.
- `disjoint_lane_count` is order-independent: it counts lanes whose files overlap no other lane.
- Regression tests lock `lessons_max` in the session-lessons hook and env rows in the lead brief.
