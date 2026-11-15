-- Fleet ledger foundation: an isolated schema for multi-agent task coordination.
-- Additive only. Rollback: drop schema fleet_ledger cascade; select pgmq.drop_queue('fleet_tasks'); drop extension pgmq;

create schema if not exists fleet_ledger;
revoke all on schema fleet_ledger from public, anon, authenticated, service_role;
alter default privileges in schema fleet_ledger revoke all on tables from public, anon, authenticated, service_role;
alter default privileges in schema fleet_ledger revoke all on functions from public, anon, authenticated, service_role;
alter default privileges in schema fleet_ledger revoke all on sequences from public, anon, authenticated, service_role;

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
  seq bigint generated always as identity primary key,
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
  last_hash text;
begin
  perform pg_advisory_xact_lock(hashtext('fleet_ledger.events'));
  select e.hash into last_hash from fleet_ledger.events e order by e.seq desc limit 1;
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

revoke all on all tables in schema fleet_ledger from public, anon, authenticated, service_role;
revoke all on all functions in schema fleet_ledger from public, anon, authenticated, service_role;

create extension if not exists pgmq;
select pgmq.create('fleet_tasks');

insert into fleet_ledger.events (kind, payload)
values ('ledger_created', '{"note": "foundation schema applied"}'::jsonb);
