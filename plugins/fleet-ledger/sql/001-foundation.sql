-- Fleet ledger foundation: an isolated schema for multi-agent task coordination.
-- Additive only. Rollback: drop schema fleet_ledger cascade; select pgmq.drop_queue('fleet_tasks'); drop extension pgmq;
-- Runs in one transaction: a failure at any step leaves nothing behind, so the file can be run again.

begin;

create schema if not exists fleet_ledger;
revoke all on schema fleet_ledger from public;
alter default privileges in schema fleet_ledger revoke all on tables from public;
alter default privileges in schema fleet_ledger revoke all on functions from public;
alter default privileges in schema fleet_ledger revoke all on sequences from public;

-- Application roles exist on Supabase and may be absent elsewhere, so each is revoked only when present.
do $$
declare
  app_role text;
begin
  foreach app_role in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = app_role) then
      execute format('revoke all on schema fleet_ledger from %I', app_role);
      execute format('alter default privileges in schema fleet_ledger revoke all on tables from %I', app_role);
      execute format('alter default privileges in schema fleet_ledger revoke all on functions from %I', app_role);
      execute format('alter default privileges in schema fleet_ledger revoke all on sequences from %I', app_role);
    end if;
  end loop;
end;
$$;

create table fleet_ledger.seats (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  model_family text not null,
  db_role name unique,
  capability_card jsonb not null default '{}'::jsonb,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table fleet_ledger.tasks (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  done_when text not null check (length(trim(done_when)) > 0),
  risk_tier text not null check (risk_tier in ('t0', 't1', 't2')),
  roles_needed text[] not null default '{}',
  roadmap_ref text,
  body jsonb not null default '{}'::jsonb,
  status text not null default 'queued'
    check (status in ('queued', 'claimed', 'done', 'parked', 'dead_letter', 'cancelled')),
  owner_seat uuid references fleet_ledger.seats (id),
  lease_version integer not null default 0,
  lease_until timestamptz,
  redeliveries integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index tasks_status_idx on fleet_ledger.tasks (status, created_at);
create index tasks_owner_idx on fleet_ledger.tasks (owner_seat);

create table fleet_ledger.votes (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references fleet_ledger.tasks (id),
  seat_id uuid not null references fleet_ledger.seats (id),
  approve boolean not null,
  rationale text,
  cast_at timestamptz not null default now(),
  unique (task_id, seat_id)
);
create index votes_seat_idx on fleet_ledger.votes (seat_id);

create table fleet_ledger.events (
  seq bigint primary key,  -- set by the events_chain trigger, inside the chain lock
  at timestamptz not null default now(),
  actor text not null default current_user,
  kind text not null,
  task_id uuid,
  payload jsonb not null default '{}'::jsonb,
  prev_hash text not null,
  hash text not null
);

create function fleet_ledger.events_chain() returns trigger
language plpgsql set search_path = '' as $$
declare
  last_seq bigint;
  last_hash text;
begin
  -- The sequence number is assigned here, after the lock, so sequence order always matches chain order.
  perform pg_advisory_xact_lock(hashtext('fleet_ledger.events'));
  select e.seq, e.hash into last_seq, last_hash from fleet_ledger.events e order by e.seq desc limit 1;
  new.seq := coalesce(last_seq, 0) + 1;
  new.prev_hash := coalesce(last_hash, 'genesis');
  new.hash := encode(sha256(convert_to(
    new.prev_hash || '|' || new.at::text || '|' || new.actor || '|' || new.kind || '|'
    || coalesce(new.task_id::text, '') || '|' || new.payload::text, 'UTF8')), 'hex');
  return new;
end;
$$;

create function fleet_ledger.events_immutable() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'fleet_ledger.events is append-only';
end;
$$;

create trigger events_chain before insert on fleet_ledger.events
  for each row execute function fleet_ledger.events_chain();
create trigger events_no_change before update or delete on fleet_ledger.events
  for each row execute function fleet_ledger.events_immutable();
create trigger events_no_truncate before truncate on fleet_ledger.events
  for each statement execute function fleet_ledger.events_immutable();

alter table fleet_ledger.seats enable row level security;
alter table fleet_ledger.tasks enable row level security;
alter table fleet_ledger.votes enable row level security;
alter table fleet_ledger.events enable row level security;

revoke all on all tables in schema fleet_ledger from public;
revoke all on all functions in schema fleet_ledger from public;

create extension if not exists pgmq;
select pgmq.create('fleet_tasks');

-- Lock the queue down the same way as the ledger schema. A database may grant its application
-- roles access to pgmq (for example when queues are exposed through an API), so this does not rely on defaults.
alter table pgmq.q_fleet_tasks enable row level security;
alter table pgmq.a_fleet_tasks enable row level security;
revoke all on pgmq.q_fleet_tasks, pgmq.a_fleet_tasks from public;
do $$
declare
  app_role text;
begin
  foreach app_role in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = app_role) then
      execute format('revoke all on pgmq.q_fleet_tasks, pgmq.a_fleet_tasks from %I', app_role);
    end if;
  end loop;
end;
$$;

insert into fleet_ledger.events (kind, payload)
values ('ledger_created', '{"note": "foundation schema applied"}'::jsonb);

commit;
