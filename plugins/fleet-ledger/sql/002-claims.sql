-- Fleet ledger 0.2.0: claim, heartbeat, complete and release, with expiring leases.
-- Requires 001-foundation.sql. Additive only: three nullable columns, new functions, one group role.
-- Rollback (in one transaction):
--   drop function fleet_ledger.claim_next(uuid, interval, uuid), fleet_ledger.heartbeat(uuid, integer, interval, uuid),
--     fleet_ledger.complete(uuid, integer, jsonb, text, uuid), fleet_ledger.release(uuid, integer, text, uuid),
--     fleet_ledger.sweep_expired(), fleet_ledger.acting_seat(uuid), fleet_ledger.check_lease(interval),
--     fleet_ledger.max_redeliveries(), fleet_ledger.max_result_bytes();
--   alter table fleet_ledger.tasks drop column claimed_at, drop column completed_at, drop column result;
--   revoke usage on schema fleet_ledger from fleet_seat; drop role fleet_seat;  -- only once no seat role is a member
-- Runs in one transaction: a failure at any step leaves nothing behind.

begin;

-- Seats log in with their own roles (a later release), each a member of this group. The group gets
-- execute on the four seat functions below and nothing else: no table in the schema is granted to it.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'fleet_seat') then
    create role fleet_seat nologin;
  end if;
end;
$$;
grant usage on schema fleet_ledger to fleet_seat;

alter table fleet_ledger.tasks
  add column if not exists claimed_at timestamptz,
  add column if not exists completed_at timestamptz,
  add column if not exists result jsonb;

create index if not exists tasks_lease_idx on fleet_ledger.tasks (lease_until) where status = 'claimed';

-- Limits, kept in one place so the tests and the docs read the same numbers.
create function fleet_ledger.max_redeliveries() returns integer
language sql immutable set search_path = '' as $$ select 3 $$;

create function fleet_ledger.max_result_bytes() returns integer
language sql immutable set search_path = '' as $$ select 65536 $$;

create function fleet_ledger.check_lease(p_lease interval) returns void
language plpgsql immutable set search_path = '' as $$
begin
  if p_lease is null or p_lease < interval '1 minute' or p_lease > interval '4 hours' then
    raise exception 'a lease must be between 1 minute and 4 hours' using errcode = '22023';
  end if;
end;
$$;

-- Which seat is acting. A seat login (seats.db_role = session_user) always acts as itself.
-- Any other caller must belong to the role that owns the schema (the router), and must name the seat.
-- session_user is used because the seat functions run as their owner; SET ROLE does not change it.
create function fleet_ledger.acting_seat(p_seat uuid) returns fleet_ledger.seats
language plpgsql stable set search_path = '' as $$
declare
  chosen fleet_ledger.seats;
  schema_owner oid;
begin
  select s.* into chosen from fleet_ledger.seats s where s.db_role = session_user;
  if found then
    if p_seat is not null and p_seat <> chosen.id then
      raise exception 'a seat may act only for itself' using errcode = '42501';
    end if;
  else
    select n.nspowner into schema_owner from pg_catalog.pg_namespace n where n.nspname = 'fleet_ledger';
    if not pg_catalog.pg_has_role(session_user, schema_owner, 'MEMBER') then
      raise exception 'the caller is not a registered seat' using errcode = '42501';
    end if;
    if p_seat is null then
      raise exception 'name the seat to act for' using errcode = '22004';
    end if;
    select s.* into chosen from fleet_ledger.seats s where s.id = p_seat;
    if not found then
      raise exception 'unknown seat %', p_seat using errcode = 'P0002';
    end if;
  end if;
  if not chosen.active then
    raise exception 'seat % is not active', chosen.name using errcode = '42501';
  end if;
  return chosen;
end;
$$;

-- Puts every task whose lease has lapsed back in the queue, or in dead_letter once it has lapsed
-- max_redeliveries() times. Runs inside claim_next (check on read), so no scheduler is needed;
-- a pg_cron job may also call it. Returns how many tasks it moved.
create function fleet_ledger.sweep_expired() returns integer
language plpgsql security definer set search_path = '' as $$
declare
  lapsed record;
  moved integer := 0;
  next_status text;
begin
  for lapsed in
    select t.id, t.lease_version, t.redeliveries, s.name as seat_name
      from fleet_ledger.tasks t
      left join fleet_ledger.seats s on s.id = t.owner_seat
     where t.status = 'claimed' and t.lease_until < now()
     order by t.lease_until
       for update of t skip locked
  loop
    next_status := case when lapsed.redeliveries + 1 >= fleet_ledger.max_redeliveries()
                        then 'dead_letter' else 'queued' end;
    update fleet_ledger.tasks t
       set status = next_status, owner_seat = null, lease_until = null,
           redeliveries = t.redeliveries + 1, updated_at = now()
     where t.id = lapsed.id;
    insert into fleet_ledger.events (actor, kind, task_id, payload)
    values ('sweeper', case when next_status = 'dead_letter' then 'task_dead_lettered' else 'lease_expired' end,
            lapsed.id, jsonb_build_object('lease_version', lapsed.lease_version, 'seat', lapsed.seat_name,
                                          'redeliveries', lapsed.redeliveries + 1));
    moved := moved + 1;
  end loop;
  return moved;
end;
$$;

-- Claims the oldest queued task this seat may take (its roles cover the task's roles_needed),
-- or the named task when p_task is given. Atomic: two seats never get the same task, because the
-- row is locked and rows other callers hold are skipped. Returns no row when nothing is claimable.
-- The returned lease_version fences every later call: a seat that lost its lease cannot act on the task.
create function fleet_ledger.claim_next(p_seat uuid default null, p_lease interval default interval '2 hours',
                                        p_task uuid default null)
returns table (task_id uuid, lease_version integer, lease_until timestamptz, title text, done_when text,
               risk_tier text, roles_needed text[], roadmap_ref text, body jsonb)
language plpgsql security definer set search_path = '' as $$
#variable_conflict use_column
declare
  seat fleet_ledger.seats;
  seat_roles text[];
  picked fleet_ledger.tasks;
begin
  perform fleet_ledger.check_lease(p_lease);
  seat := fleet_ledger.acting_seat(p_seat);
  perform fleet_ledger.sweep_expired();

  seat_roles := array(select jsonb_array_elements_text(
    case when jsonb_typeof(seat.capability_card -> 'roles') = 'array'
         then seat.capability_card -> 'roles' else '[]'::jsonb end));

  select t.* into picked
    from fleet_ledger.tasks t
   where t.status = 'queued'
     and t.roles_needed <@ seat_roles
     and (p_task is null or t.id = p_task)
   order by t.created_at, t.id
   limit 1
     for update of t skip locked;
  if not found then
    return;
  end if;

  update fleet_ledger.tasks t
     set status = 'claimed', owner_seat = seat.id, lease_version = t.lease_version + 1,
         lease_until = now() + p_lease, claimed_at = now(), updated_at = now()
   where t.id = picked.id
  returning t.* into picked;

  insert into fleet_ledger.events (actor, kind, task_id, payload)
  values (seat.name, 'task_claimed', picked.id,
          jsonb_build_object('lease_version', picked.lease_version, 'lease_until', picked.lease_until));

  return query select picked.id, picked.lease_version, picked.lease_until, picked.title, picked.done_when,
                      picked.risk_tier, picked.roles_needed, picked.roadmap_ref, picked.body;
end;
$$;

-- Renews the lease. Fails with SQLSTATE 55000 when the seat no longer holds the task at that
-- lease version, including when the lease has already lapsed: the seat must stop work on it.
-- Heartbeats are not written to the event log, to keep the chain small.
create function fleet_ledger.heartbeat(p_task uuid, p_lease_version integer,
                                       p_lease interval default interval '2 hours', p_seat uuid default null)
returns timestamptz
language plpgsql security definer set search_path = '' as $$
declare
  seat fleet_ledger.seats;
  new_until timestamptz;
begin
  perform fleet_ledger.check_lease(p_lease);
  seat := fleet_ledger.acting_seat(p_seat);
  update fleet_ledger.tasks t
     set lease_until = now() + p_lease, updated_at = now()
   where t.id = p_task and t.status = 'claimed' and t.owner_seat = seat.id
     and t.lease_version = p_lease_version and t.lease_until >= now()
  returning t.lease_until into new_until;
  if not found then
    raise exception 'lease lost: seat % does not hold task % at lease version %', seat.name, p_task, p_lease_version
      using errcode = '55000';
  end if;
  return new_until;
end;
$$;

-- Finishes the task. p_outcome 'done' means the done_when line is met; 'parked' means it waits on
-- something outside the fleet (a gate the owner holds, a missing input). The result is a JSON object
-- of at most max_result_bytes(). Same fencing as heartbeat.
create function fleet_ledger.complete(p_task uuid, p_lease_version integer, p_result jsonb default '{}'::jsonb,
                                      p_outcome text default 'done', p_seat uuid default null)
returns void
language plpgsql security definer set search_path = '' as $$
declare
  seat fleet_ledger.seats;
begin
  if p_outcome is null or p_outcome not in ('done', 'parked') then
    raise exception 'outcome must be done or parked' using errcode = '22023';
  end if;
  if p_result is null or jsonb_typeof(p_result) <> 'object' then
    raise exception 'result must be a JSON object' using errcode = '22023';
  end if;
  if octet_length(p_result::text) > fleet_ledger.max_result_bytes() then
    raise exception 'result is larger than % bytes', fleet_ledger.max_result_bytes() using errcode = '54000';
  end if;
  seat := fleet_ledger.acting_seat(p_seat);
  update fleet_ledger.tasks t
     set status = p_outcome, result = p_result, completed_at = now(), lease_until = null, updated_at = now()
   where t.id = p_task and t.status = 'claimed' and t.owner_seat = seat.id
     and t.lease_version = p_lease_version and t.lease_until >= now();
  if not found then
    raise exception 'lease lost: seat % does not hold task % at lease version %', seat.name, p_task, p_lease_version
      using errcode = '55000';
  end if;
  insert into fleet_ledger.events (actor, kind, task_id, payload)
  values (seat.name, 'task_' || p_outcome, p_task,
          jsonb_build_object('lease_version', p_lease_version, 'result', p_result));
end;
$$;

-- Hands the task back to the queue without counting a redelivery, for a seat that cannot finish it.
create function fleet_ledger.release(p_task uuid, p_lease_version integer, p_reason text default null,
                                     p_seat uuid default null)
returns void
language plpgsql security definer set search_path = '' as $$
declare
  seat fleet_ledger.seats;
begin
  seat := fleet_ledger.acting_seat(p_seat);
  update fleet_ledger.tasks t
     set status = 'queued', owner_seat = null, lease_until = null, updated_at = now()
   where t.id = p_task and t.status = 'claimed' and t.owner_seat = seat.id
     and t.lease_version = p_lease_version and t.lease_until >= now();
  if not found then
    raise exception 'lease lost: seat % does not hold task % at lease version %', seat.name, p_task, p_lease_version
      using errcode = '55000';
  end if;
  insert into fleet_ledger.events (actor, kind, task_id, payload)
  values (seat.name, 'task_released', p_task,
          jsonb_build_object('lease_version', p_lease_version, 'reason', left(coalesce(p_reason, ''), 500)));
end;
$$;

-- Execute rights: seats get the four seat functions; everything else stays with the schema owner.
revoke all on all functions in schema fleet_ledger from public;
do $$
declare
  app_role text;
begin
  foreach app_role in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = app_role) then
      execute format('revoke all on all functions in schema fleet_ledger from %I', app_role);
    end if;
  end loop;
end;
$$;
grant execute on function fleet_ledger.claim_next(uuid, interval, uuid),
                          fleet_ledger.heartbeat(uuid, integer, interval, uuid),
                          fleet_ledger.complete(uuid, integer, jsonb, text, uuid),
                          fleet_ledger.release(uuid, integer, text, uuid)
  to fleet_seat;

insert into fleet_ledger.events (kind, payload)
values ('claims_installed', '{"release": "0.2.0"}'::jsonb);

commit;
