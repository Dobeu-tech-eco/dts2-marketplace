# Backups and migrations: <project>

## Backup schedule

| field | value |
|---|---|
| data stores | <database, object storage, anything not rebuilt from git> |
| method | <provider snapshot, scheduled dump, point-in-time recovery> |
| schedule | daily, plus one immediately before any destructive migration |
| retention | <days> |
| copy location | <a place the app's own credentials cannot delete from> |
| who is told when a backup fails | see `ops/monitoring.md` alert route |

## Restore test

A backup counts only after it has been restored. Restore into a scratch database, run a row count and one known query, then delete the scratch copy.

| date | backup used | restored to | result | by |
|---|---|---|---|---|
| <YYYY-MM-DD> | <id> | <scratch target> | pass / fail | <name> |

Repeat after any change to the backup method and at least once a quarter.

## Migrations: expand, then contract

Never ship a schema change the previous app version cannot run against, because a rollback puts the old code back on the new schema.

1. Expand: add the new column, table or index. Keep everything the old code reads. Deploy.
2. Migrate: write to both shapes, backfill old rows in batches, verify counts match.
3. Switch: read from the new shape. Deploy. Keep the old shape in place for one full watch window.
4. Contract: drop the old column or table in a later release, after the rollback window has passed.

Rules:
- A destructive step (drop, truncate, type narrowing, rename) needs a fresh backup taken and checked immediately before it, and the backup id written in the change receipt.
- Each migration is idempotent and has a written way back, or says plainly that it has none.
- Large backfills run in batches with a pause between them, never in one transaction.
- The agent does not run a destructive migration against production. It prepares the change and the backup command; a person with the scoped credential from `ops/credential-handoff.md` runs it.
