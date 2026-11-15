---
name: status
description: "Read-only health check of a fleet ledger database: tables present, event chain intact, application roles locked out, queue present. Use for fleet ledger status or to verify the foundation after it is applied."
---

# Fleet ledger status (read-only)

`/fleet-ledger:status` checks one database and changes nothing. Ask which database to check when the user has not named one. Never guess a project.

## 1. Confirm the foundation is there

The check in step 2 raises an error when the schema or the queue extension is missing, so run this first:

```sql
select to_regclass('fleet_ledger.events') is not null as foundation_applied,
       exists (select 1 from pg_extension where extname = 'pgmq') as pgmq_installed;
```

If either value is `false`, say the foundation is not applied, point to `sql/001-foundation.sql`, and stop. Do not apply it unless the owner asks.

## 2. Run the check

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
union all select 'queue', coalesce((select string_agg(queue_name, ', ') from pgmq.list_queues()), 'missing')
union all select 'queue_locked_down', (not exists (
    select 1 from pg_roles r, pg_class c join pg_namespace n on n.oid = c.relnamespace
    where r.rolname in ('anon', 'authenticated', 'service_role')
      and n.nspname = 'pgmq' and c.relname in ('q_fleet_tasks', 'a_fleet_tasks')
      and (has_table_privilege(r.rolname, c.oid, 'select') or has_table_privilege(r.rolname, c.oid, 'insert')
        or has_table_privilege(r.rolname, c.oid, 'update') or has_table_privilege(r.rolname, c.oid, 'delete'))))::text;
```

## 3. Report

One line per check, then one verdict line.

| Check | Healthy value |
|---|---|
| `tables` | `events`, `seats`, `tasks`, `votes`, each with `rls=true` |
| `chain_ok` | `true` |
| `app_roles_locked_out` | `true` |
| `queue` | includes `fleet_tasks` |
| `queue_locked_down` | `true` |

- Every check healthy → `Fleet ledger: healthy.`
- `chain_ok` is `false` → `Fleet ledger: event chain broken.` Report it to the owner and stop. Do not repair it.
- `tables` is `missing` or lists fewer than four tables → `Fleet ledger: foundation incomplete.` Report it to the owner and stop.

`chain_ok` only checks that each row points at the row before it. It does not recompute hashes, so it will not catch a rewrite of the whole chain. That needs a copy of the latest hash kept outside the database, which this release does not provide.

## Guardrails

- Read-only. Never insert, update, delete, grant or run DDL from this skill.
- Never print connection strings, keys or passwords.
