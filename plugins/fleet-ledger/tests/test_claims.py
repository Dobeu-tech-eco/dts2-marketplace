"""Tests for 002-claims.sql and the Python client: atomic claims, leases, fencing and seat identity."""
from __future__ import annotations

import json
import threading
from datetime import timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fleet_ledger import ClaimedTask, LeaseLostError, LedgerClient
from psycopg import errors

SHORT_LEASE: timedelta = timedelta(minutes=5)
SEAT_LOGIN: str = "fleet_ledger_test_seat"
MAX_REDELIVERIES: int = 3


def _seat(conn: psycopg.Connection, name: str, roles: list[str], active: bool = True) -> UUID:
    row = conn.execute(
        "insert into fleet_ledger.seats (name, model_family, capability_card, active) values (%s, 'test', %s, %s)"
        " returning id",
        (name, json.dumps({"roles": roles}), active),
    ).fetchone()
    return row[0]


def _task(conn: psycopg.Connection, title: str, roles_needed: list[str] | None = None) -> UUID:
    row = conn.execute(
        "insert into fleet_ledger.tasks (title, done_when, risk_tier, roles_needed) values (%s, 'done', 't0', %s)"
        " returning id",
        (title, roles_needed or []),
    ).fetchone()
    return row[0]


def _lapse(conn: psycopg.Connection, task_id: UUID) -> None:
    conn.execute("update fleet_ledger.tasks set lease_until = now() - interval '1 second' where id = %s", (task_id,))


def _task_row(conn: psycopg.Connection, task_id: UUID) -> dict[str, Any]:
    cur = conn.cursor(row_factory=psycopg.rows.dict_row)
    return cur.execute("select * from fleet_ledger.tasks where id = %s", (task_id,)).fetchone()


def _event_kinds(conn: psycopg.Connection) -> list[str]:
    return [row[0] for row in conn.execute("select kind from fleet_ledger.events order by seq").fetchall()]


@pytest.fixture()
def conn(ledger_dsn: str) -> psycopg.Connection:
    with psycopg.connect(ledger_dsn, autocommit=True) as connection:
        yield connection


def test_install_records_event_and_keeps_chain(conn: psycopg.Connection) -> None:
    assert _event_kinds(conn) == ["ledger_created", "claims_installed"]
    intact: bool = conn.execute(
        "select bool_and(hash = encode(sha256(convert_to(prev_hash || '|' || at::text || '|' || actor || '|' || kind"
        " || '|' || coalesce(task_id::text, '') || '|' || payload::text, 'UTF8')), 'hex')"
        " and prev_hash = coalesce(lag_hash, 'genesis'))"
        " from (select *, lag(hash) over (order by seq) as lag_hash from fleet_ledger.events) e"
    ).fetchone()[0]
    assert intact


def test_claim_takes_oldest_task_the_seat_can_do(conn: psycopg.Connection) -> None:
    reviewer = _seat(conn, "reviewer", ["reviewer"])
    _task(conn, "build only", ["builder"])
    open_task = _task(conn, "anyone")
    claimed = LedgerClient(conn, reviewer).claim_next(SHORT_LEASE)
    assert claimed is not None and claimed.task_id == open_task
    assert claimed.lease_version == 1
    assert LedgerClient(conn, reviewer).claim_next(SHORT_LEASE) is None


def test_two_seats_never_get_the_same_task(ledger_dsn: str, conn: psycopg.Connection) -> None:
    first_seat = _seat(conn, "first", [])
    second_seat = _seat(conn, "second", [])
    only_task = _task(conn, "only one")
    with psycopg.connect(ledger_dsn) as first, psycopg.connect(ledger_dsn) as second:
        held = LedgerClient(first, first_seat).claim_next(SHORT_LEASE)
        assert held is not None and held.task_id == only_task
        assert LedgerClient(second, second_seat).claim_next(SHORT_LEASE) is None
        first.commit()
        second.rollback()
    assert _task_row(conn, only_task)["owner_seat"] == first_seat


def test_skip_locked_hands_the_next_task_to_a_second_seat(ledger_dsn: str, conn: psycopg.Connection) -> None:
    first_seat = _seat(conn, "first", [])
    second_seat = _seat(conn, "second", [])
    _task(conn, "one")
    _task(conn, "two")
    claimed: list[ClaimedTask | None] = []
    with psycopg.connect(ledger_dsn) as first, psycopg.connect(ledger_dsn) as second:
        a = LedgerClient(first, first_seat).claim_next(SHORT_LEASE)
        # The second claim skips the locked row, then waits on the event-chain lock until the first commits.
        worker = threading.Thread(target=lambda: claimed.append(LedgerClient(second, second_seat).claim_next(SHORT_LEASE)))
        worker.start()
        worker.join(timeout=1)
        first.commit()
        worker.join(timeout=10)
        second.commit()
    b = claimed[0]
    assert a is not None and b is not None and a.task_id != b.task_id


def test_heartbeat_renews_and_wrong_version_is_rejected(conn: psycopg.Connection) -> None:
    seat = _seat(conn, "worker", [])
    _task(conn, "work")
    client = LedgerClient(conn, seat)
    task = client.claim_next(timedelta(minutes=1))
    assert client.heartbeat(task, timedelta(hours=1)) > task.lease_until
    stale = type(task)(**{**task.__dict__, "lease_version": task.lease_version + 1})
    with pytest.raises(LeaseLostError):
        client.heartbeat(stale)


def test_lapsed_lease_goes_back_to_queue_and_old_holder_is_fenced(conn: psycopg.Connection) -> None:
    slow = _seat(conn, "slow", [])
    fast = _seat(conn, "fast", [])
    task_id = _task(conn, "work")
    old = LedgerClient(conn, slow).claim_next(SHORT_LEASE)
    _lapse(conn, task_id)
    with pytest.raises(LeaseLostError):
        LedgerClient(conn, slow).heartbeat(old)
    new = LedgerClient(conn, fast).claim_next(SHORT_LEASE)
    assert new is not None and new.task_id == task_id and new.lease_version == old.lease_version + 1
    assert _task_row(conn, task_id)["redeliveries"] == 1
    with pytest.raises(LeaseLostError):
        LedgerClient(conn, slow).complete(old, {"note": "too late"})
    assert "lease_expired" in _event_kinds(conn)


def test_task_dead_letters_after_max_redeliveries(conn: psycopg.Connection) -> None:
    seat = _seat(conn, "flaky", [])
    task_id = _task(conn, "cursed")
    client = LedgerClient(conn, seat)
    for _ in range(MAX_REDELIVERIES - 1):
        assert client.claim_next(SHORT_LEASE) is not None
        _lapse(conn, task_id)
    assert client.claim_next(SHORT_LEASE) is not None
    _lapse(conn, task_id)
    assert conn.execute("select fleet_ledger.sweep_expired()").fetchone()[0] == 1
    row = _task_row(conn, task_id)
    assert (row["status"], row["redeliveries"]) == ("dead_letter", MAX_REDELIVERIES)
    assert client.claim_next(SHORT_LEASE) is None


def test_complete_and_park_record_result(conn: psycopg.Connection) -> None:
    seat = _seat(conn, "worker", [])
    done_id = _task(conn, "finish me")
    park_id = _task(conn, "needs the owner")
    client = LedgerClient(conn, seat)
    client.complete(client.claim_next(SHORT_LEASE), {"pr": 7})
    client.complete(client.claim_next(SHORT_LEASE), {"waits_on": "owner"}, outcome="parked")
    done, parked = _task_row(conn, done_id), _task_row(conn, park_id)
    assert (done["status"], done["result"], done["lease_until"]) == ("done", {"pr": 7}, None)
    assert parked["status"] == "parked" and parked["owner_seat"] == seat
    assert _event_kinds(conn)[-4:] == ["task_claimed", "task_done", "task_claimed", "task_parked"]


def test_complete_rejects_bad_outcome_and_oversized_result(conn: psycopg.Connection) -> None:
    seat = _seat(conn, "worker", [])
    _task(conn, "work")
    client = LedgerClient(conn, seat)
    task = client.claim_next(SHORT_LEASE)
    with pytest.raises(errors.InvalidParameterValue):
        client.complete(task, {}, outcome="shipped")  # type: ignore[arg-type]
    with pytest.raises(errors.ProgramLimitExceeded):
        client.complete(task, {"blob": "x" * 70000})


def test_release_requeues_without_counting_a_redelivery(conn: psycopg.Connection) -> None:
    seat = _seat(conn, "worker", [])
    task_id = _task(conn, "work")
    client = LedgerClient(conn, seat)
    client.release(client.claim_next(SHORT_LEASE), "missing input")
    row = _task_row(conn, task_id)
    assert (row["status"], row["owner_seat"], row["redeliveries"]) == ("queued", None, 0)


def test_lease_must_be_within_bounds(conn: psycopg.Connection) -> None:
    seat = _seat(conn, "worker", [])
    _task(conn, "work")
    with pytest.raises(errors.InvalidParameterValue):
        LedgerClient(conn, seat).claim_next(timedelta(hours=5))
    with pytest.raises(errors.InvalidParameterValue):
        LedgerClient(conn, seat).claim_next(timedelta(seconds=10))


def test_inactive_seat_and_router_without_seat_are_refused(conn: psycopg.Connection) -> None:
    retired = _seat(conn, "retired", [], active=False)
    _task(conn, "work")
    with pytest.raises(errors.InsufficientPrivilege):
        LedgerClient(conn, retired).claim_next(SHORT_LEASE)
    with pytest.raises(errors.NullValueNotAllowed):
        LedgerClient(conn).claim_next(SHORT_LEASE)


def test_seat_login_acts_only_as_itself_and_cannot_read_tables(conn: psycopg.Connection) -> None:
    conn.execute(
        f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{SEAT_LOGIN}')"
        f" then create role {SEAT_LOGIN} nologin; end if; end $$"
    )
    conn.execute(f"grant fleet_seat to {SEAT_LOGIN}")
    mine = _seat(conn, "mine", [])
    other = _seat(conn, "other", [])
    conn.execute("update fleet_ledger.seats set db_role = %s where id = %s", (SEAT_LOGIN, mine))
    _task(conn, "work")
    conn.execute(f"set session authorization {SEAT_LOGIN}")
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            LedgerClient(conn, other).claim_next(SHORT_LEASE)
        claimed = LedgerClient(conn).claim_next(SHORT_LEASE)
        assert claimed is not None
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("select count(*) from fleet_ledger.tasks")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("select fleet_ledger.sweep_expired()")
    finally:
        conn.execute("reset session authorization")
    assert _task_row(conn, claimed.task_id)["owner_seat"] == mine


@pytest.mark.parametrize("app_role", ["anon", "authenticated", "service_role"])
def test_application_roles_cannot_call_seat_functions(conn: psycopg.Connection, app_role: str) -> None:
    conn.execute(f"set session authorization {app_role}")
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("select * from fleet_ledger.claim_next(null)")
    finally:
        conn.execute("reset session authorization")
