# autopilot - section 5, final report

## 5. Final report
Print the progress table, then one line each: steps done, parked (with action-item ids and the command that unblocks each), PRs merged, council decisions (one line each: step, tally, decision, path to the record so the user can read the rationale), branches left (should be only `main` and `dev`; run `/dts2-harness:ship` step 7's sweep with autopilot's no-ask rule if any step branch survived), open harness lessons for the evolve sweep, the task ledger (`.harness/runs/<stamp>/task-ledger.md`, its count line and each open PR with its blocking items), and `/dts2-harness:check-in` for the full picture.
