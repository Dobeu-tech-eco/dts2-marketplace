---
name: status
description: "Read-only health check of a fleet ledger database: tables present, event chain intact, application roles locked out, queue present. Use for fleet ledger status or to verify the foundation after it is applied."
---

# Fleet ledger status (read-only)

`/fleet-ledger:status` checks one database and changes nothing. Ask which database to check when the user has not named one. Never guess a project.

## 1. Run the check

Run this one query through whatever database tool the session has (a Supabase connector, `psql`, or another SQL client):

```sql
select 'tables' as check, coalesce(string_agg(tablename || ' rls=' || rowsecurity, ', ' order by tablename), 'missing') as result
  from pg_tables where schemaname = 'fleet_ledger'
union all select 'event_count', count(*)::text from fleet_ledger.events
union all select 'chain_ok', coalesce(bool_and(prev_hash = coalesce(lag_hash, 'genesis'))::text, 'empty')
  from (select prev_hash, lag(hash) over (order by seq) as lag_hash from fleet_ledger.events) t
union all select 'app_roles_locked_out', (not exists (
    select 1 from pg_roles r where r.rolname in ('anon', 'authenticated', 'service_role')
      and has_schema_privilege(r.rolname, 'fleet_ledger', 'usage')))::text
union all select 'queue', coalesce((select string_agg(queue_name, ', ') from pgmq.list_queues()), 'missing');
```

## 2. Report

One line per check, then one verdict line.

| Check | Healthy value |
|---|---|
| `tables` | `events`, `seats`, `tasks`, `votes`, each with `rls=true` |
| `chain_ok` | `true` |
| `app_roles_locked_out` | `true` |
| `queue` | includes `fleet_tasks` |

- Every check healthy → `Fleet ledger: healthy.`
- `chain_ok` is `false` → `Fleet ledger: event chain broken.` Report it to the owner and stop. Do not repair it.
- The schema is missing → say the foundation is not applied and point to `sql/001-foundation.sql`. Do not apply it unless the owner asks.

`chain_ok` only checks that each row points at the row before it. It does not recompute hashes, so it will not catch a rewrite of the whole chain. That needs a copy of the latest hash kept outside the database, which this release does not provide.

## Guardrails

- Read-only. Never insert, update, delete, grant or run DDL from this skill.
- Never print connection strings, keys or passwords.
