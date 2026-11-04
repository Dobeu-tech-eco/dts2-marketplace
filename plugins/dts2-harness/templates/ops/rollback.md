# Rollback and post-deploy watch: <project>

## Rollback order

1. Provider instant rollback. Promote the previous good deployment through the hosting provider's rollback command or dashboard. This takes seconds and touches no code.
   - Command: <provider rollback command>
2. Feature flag off. If the change is behind a flag (see `ops/release.md`), turn it off.
3. Revert the change in git, let CI pass, deploy the revert. Slowest, so last.

A rollback does not undo a migration. Before rolling back, check whether the release included a schema change; if it did, follow the expand/contract notes in `ops/backups.md`.

## Post-deploy watch

Run for 15 to 30 minutes after every production deploy. Use a read-only credential from `ops/credential-handoff.md`.

| signal | healthy | regression |
|---|---|---|
| error rate | at or below the 24-hour baseline | more than double the baseline for 5 minutes |
| server errors (5xx) | none beyond baseline | any sustained rise |
| key route | returns 200 and the expected marker | fails twice in a row |
| new error types | none | any not seen before the deploy |

Outcome:
- Healthy for the whole window: record `watch: clean` in the deploy note and stop.
- Regression: recommend a rollback, with the signal, the time it started and the deploy it followed. The person decides; the agent does not roll back production on its own.
- New production errors: add each one as an action item, `action-items.py <repo> add Deploy "<error and first seen time>"`, so none is lost.
