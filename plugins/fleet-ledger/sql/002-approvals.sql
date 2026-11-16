-- Fleet ledger 002: the owner's approvals, recorded by the seat that heard them, readable by every seat.
-- Additive only. Needs 001-foundation.sql. Rollback:
--   drop view fleet_ledger.approvals_current; drop function fleet_ledger.record_approval(text, text, text, text, text, timestamptz, text, uuid, text, text, timestamptz);
--   drop table fleet_ledger.approvals; drop function fleet_ledger.approvals_to_event(); drop function fleet_ledger.append_only();
-- Runs in one transaction: a failure at any step leaves nothing behind, so the file can be run again.

begin;

-- One generic append-only guard, named for the table it protects.
create function fleet_ledger.append_only() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'fleet_ledger.% is append-only', tg_table_name;
end;
$$;

-- An approval is the owner's own decision on one subject, written down by the seat that received it.
-- It is append-only: a change of mind is a new row (decision 'no' or 'revoked'), never an edit.
create table fleet_ledger.approvals (
  id uuid primary key default gen_random_uuid(),
  subject text not null check (length(trim(subject)) > 0),
  task_id uuid references fleet_ledger.tasks (id),
  decision text not null check (decision in ('yes', 'no', 'revoked')),
  scope text not null default 'once' check (scope in ('once', 'standing')),
  given_by text not null check (length(trim(given_by)) > 0),
  relayed_by uuid not null references fleet_ledger.seats (id),
  channel text not null check (length(trim(channel)) > 0),
  quote text not null check (length(trim(quote)) > 0),
  evidence_ref text,
  artifact_hash text,
  given_at timestamptz not null,
  expires_at timestamptz,
  recorded_at timestamptz not null default now(),
  check (expires_at is null or expires_at > given_at),
  check (given_at <= recorded_at + interval '5 minutes')
);
comment on table fleet_ledger.approvals is
  'Owner decisions relayed by a seat. quote holds the owner''s own words verbatim; every other text column is a label.';
comment on column fleet_ledger.approvals.subject is
  'What the decision covers, as a stable key the asking seat and the reading seat both build the same way (see README).';
comment on column fleet_ledger.approvals.artifact_hash is
  'Optional: binds a yes to one exact artifact (a commit sha, a migration file hash). A yes with a hash covers nothing else.';
create index approvals_subject_idx on fleet_ledger.approvals (subject, given_at desc, recorded_at desc);
create index approvals_task_idx on fleet_ledger.approvals (task_id);
create index approvals_seat_idx on fleet_ledger.approvals (relayed_by);

create trigger approvals_no_change before update or delete on fleet_ledger.approvals
  for each row execute function fleet_ledger.append_only();
create trigger approvals_no_truncate before truncate on fleet_ledger.approvals
  for each statement execute function fleet_ledger.append_only();

-- Every approval also lands in the hash-chained event log, with a hash of the quote, so a later rewrite of the row shows.
create function fleet_ledger.approvals_to_event() returns trigger
language plpgsql set search_path = '' as $$
begin
  insert into fleet_ledger.events (kind, task_id, payload)
  values ('approval_recorded', new.task_id, jsonb_build_object(
    'approval_id', new.id,
    'subject', new.subject,
    'decision', new.decision,
    'scope', new.scope,
    'given_by', new.given_by,
    'relayed_by', (select s.name from fleet_ledger.seats s where s.id = new.relayed_by),
    'channel', new.channel,
    'artifact_hash', new.artifact_hash,
    'given_at', new.given_at,
    'expires_at', new.expires_at,
    'quote_sha256', encode(sha256(convert_to(new.quote, 'UTF8')), 'hex')));
  return new;
end;
$$;

create trigger approvals_event after insert on fleet_ledger.approvals
  for each row execute function fleet_ledger.approvals_to_event();

alter table fleet_ledger.approvals enable row level security;
revoke all on fleet_ledger.approvals from public;

-- The latest decision per subject. in_force is true only for a yes that has not expired and was not superseded.
create view fleet_ledger.approvals_current with (security_invoker = true) as
select distinct on (a.subject)
  a.subject,
  a.decision,
  a.scope,
  a.decision = 'yes' and (a.expires_at is null or a.expires_at > now()) as in_force,
  a.given_by,
  s.name as relayed_by_seat,
  s.active as relaying_seat_active,
  a.channel,
  a.quote,
  a.evidence_ref,
  a.artifact_hash,
  a.task_id,
  a.given_at,
  a.expires_at,
  a.recorded_at,
  a.id as approval_id
from fleet_ledger.approvals a
join fleet_ledger.seats s on s.id = a.relayed_by
order by a.subject, a.given_at desc, a.recorded_at desc;
revoke all on fleet_ledger.approvals_current from public;

-- The one write path for a seat. Only an active seat whose capability card says "approvals": "relay" may record,
-- so which seats can carry the owner's word is the owner's decision, made on the seats table.
create function fleet_ledger.record_approval(
  p_seat text,
  p_subject text,
  p_decision text,
  p_given_by text,
  p_quote text,
  p_given_at timestamptz,
  p_channel text,
  p_task_id uuid default null,
  p_evidence_ref text default null,
  p_artifact_hash text default null,
  p_expires_at timestamptz default null
) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  seat_id uuid;
  new_id uuid;
begin
  select s.id into seat_id from fleet_ledger.seats s
   where s.name = p_seat and s.active and s.capability_card ->> 'approvals' = 'relay';
  if seat_id is null then
    raise exception 'seat % is not an active approvals relay', p_seat;
  end if;
  insert into fleet_ledger.approvals
    (subject, task_id, decision, given_by, relayed_by, channel, quote, evidence_ref, artifact_hash, given_at, expires_at)
  values
    (p_subject, p_task_id, p_decision, p_given_by, seat_id, p_channel, p_quote, p_evidence_ref, p_artifact_hash, p_given_at, p_expires_at)
  returning id into new_id;
  return new_id;
end;
$$;
revoke all on function fleet_ledger.record_approval(text, text, text, text, text, timestamptz, text, uuid, text, text, timestamptz) from public;

-- Application roles never reach approvals (same rule as 001).
do $$
declare
  app_role text;
begin
  foreach app_role in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = app_role) then
      execute format('revoke all on fleet_ledger.approvals, fleet_ledger.approvals_current from %I', app_role);
      execute format('revoke all on function fleet_ledger.record_approval(text, text, text, text, text, timestamptz, text, uuid, text, text, timestamptz) from %I', app_role);
    end if;
  end loop;
end;
$$;

insert into fleet_ledger.events (kind, payload)
values ('approvals_installed', '{"note": "002 applied: approvals table, approvals_current view, record_approval()"}'::jsonb);

commit;
