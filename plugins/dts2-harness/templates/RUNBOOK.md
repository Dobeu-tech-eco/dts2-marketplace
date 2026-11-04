# Runbook: <project>

One page for whoever is on call. Keep it short enough to read during an incident. Update it in the same change that alters how the app is deployed, monitored or restored.

## Where things live

| thing | location |
|---|---|
| production URL | <url> |
| hosting provider and project | <provider / project name> |
| logs | <where> |
| error tracker | <tool and project> |
| uptime check | <tool and check name> |
| backups | <location and schedule> |
| secrets | <vault or provider settings; never the values> |

## First five minutes

1. Say in the incident channel that you are looking, and note the time.
2. Check the error tracker and the uptime check: is it down, slow, or throwing errors?
3. Ask what changed: the last deploy, the last migration, a flag flip, an upstream outage.
4. If the last deploy is the likely cause, roll back first (see `ops/rollback.md`), investigate second.

## Common failures

| symptom | likely cause | first action |
|---|---|---|
| <symptom> | <cause> | <action> |

## Roll back

Use the provider's instant rollback. Steps are in `ops/rollback.md`. A rollback never reverts a migration; check `ops/backups.md` before touching data.

## Restore data

Steps and the date of the last restore test are in `ops/backups.md`.

## Contacts

| role | who | how to reach |
|---|---|---|
| on call | <name> | <channel> |
| owner | <name> | <channel> |

## After the incident

Write what happened, what fixed it and what would have caught it earlier. Add each follow-up as an action item.
