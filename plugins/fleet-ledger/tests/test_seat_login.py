"""End-to-end tests of the seat runtime against a real login role: sign-in, rights check, heartbeats, fencing."""
from __future__ import annotations

import json
import secrets
import time
import uuid
from collections.abc import Iterator
from datetime import timedelta

import psycopg
import pytest
from fleet_ledger import (
    CredentialsError,
    SeatCredentials,
    SeatSession,
    SecretValue,
    run_seat_check,
)
from psycopg import sql

LEASE: timedelta = timedelta(minutes=5)
FAST_BEAT: timedelta = timedelta(milliseconds=200)
BEAT_WAIT_SECONDS: float = 1.0
TEST_SSLMODE: str = "disable"


@pytest.fixture()
def admin(ledger_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(ledger_dsn, autocommit=True) as connection:
        yield connection


@pytest.fixture()
def seat_credentials(ledger_dsn: str, admin: psycopg.Connection) -> Iterator[SeatCredentials]:
    """A throwaway login in the fleet_seat group, registered as a seat. The role is dropped afterwards;
    the seat row goes with the test database."""
    login: str = f"fleet_seat_t{uuid.uuid4().hex[:10]}"
    password: str = secrets.token_urlsafe(24)
    admin.execute(sql.SQL("create role {} login in role fleet_seat password {}").format(
        sql.Identifier(login), sql.Literal(password)))
    admin.execute(
        "insert into fleet_ledger.seats (name, model_family, capability_card, active, db_role)"
        " values (%s, 'test', %s, true, %s)", (login, json.dumps({"roles": ["builder"]}), login))
    info: dict[str, str] = psycopg.conninfo.conninfo_to_dict(ledger_dsn)
    try:
        yield SeatCredentials(login, SecretValue(password), info.get("host", "localhost"),
                              int(info.get("port", 5432)), info["dbname"], TEST_SSLMODE)
    finally:
        admin.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(login)))


def _task(admin: psycopg.Connection, title: str) -> uuid.UUID:
    row = admin.execute("insert into fleet_ledger.tasks (title, done_when, risk_tier, roles_needed)"
                        " values (%s, 'done', 't0', '{builder}') returning id", (title,)).fetchone()
    return row[0]


def test_rights_check_passes_for_a_seat_login(seat_credentials: SeatCredentials) -> None:
    with SeatSession.from_credentials(seat_credentials) as seat:
        results = run_seat_check(seat.connection)
    assert [(r.name, r.passed) for r in results] == [
        ("autocommit", True), ("rights_scoped", True), ("claim_ok", True), ("tables_denied", True),
        ("other_seat_denied", True)]


def test_rights_check_fails_for_an_over_granted_login(seat_credentials: SeatCredentials,
                                                      admin: psycopg.Connection) -> None:
    admin.execute(sql.SQL("alter role {} bypassrls").format(sql.Identifier(seat_credentials.login)))
    with SeatSession.from_credentials(seat_credentials) as seat:
        results = {r.name: r for r in run_seat_check(seat.connection)}
    assert not results["rights_scoped"].passed and "bypasses RLS" in results["rights_scoped"].detail


def test_rights_check_fails_without_autocommit(seat_credentials: SeatCredentials) -> None:
    with SeatSession.from_credentials(seat_credentials) as seat:
        seat.connection.autocommit = False
        results = {r.name: r for r in run_seat_check(seat.connection)}
        seat.connection.rollback()
    assert not results["autocommit"].passed


def test_rights_check_takes_no_real_work(seat_credentials: SeatCredentials, admin: psycopg.Connection) -> None:
    task_id = _task(admin, "real work")
    with SeatSession.from_credentials(seat_credentials) as seat:
        run_seat_check(seat.connection)
    status = admin.execute("select status from fleet_ledger.tasks where id = %s", (task_id,)).fetchone()[0]
    assert status == "queued"


def test_seat_claims_keeps_alive_and_completes(seat_credentials: SeatCredentials,
                                               admin: psycopg.Connection) -> None:
    task_id = _task(admin, "build it")
    with SeatSession.from_credentials(seat_credentials) as seat:
        task = seat.claim(LEASE)
        assert task is not None and task.task_id == task_id
        with seat.keep_alive(task, LEASE, FAST_BEAT) as beat:
            time.sleep(BEAT_WAIT_SECONDS)
        assert beat.renewals >= 1 and not beat.lost
        seat.complete(task, {"summary": "built"})
    row = admin.execute("select status, owner_seat is not null, result from fleet_ledger.tasks where id = %s",
                        (task_id,)).fetchone()
    assert row[0] == "done" and row[2] == {"summary": "built"}


def test_claim_is_visible_at_once_because_calls_commit(seat_credentials: SeatCredentials,
                                                       admin: psycopg.Connection) -> None:
    task_id = _task(admin, "visible")
    with SeatSession.from_credentials(seat_credentials) as seat:
        assert seat.claim(LEASE) is not None
        status = admin.execute("select status from fleet_ledger.tasks where id = %s", (task_id,)).fetchone()[0]
        assert status == "claimed"


def test_keeper_stops_when_the_lease_is_lost(seat_credentials: SeatCredentials, admin: psycopg.Connection) -> None:
    task_id = _task(admin, "taken away")
    with SeatSession.from_credentials(seat_credentials) as seat:
        task = seat.claim(LEASE)
        admin.execute("update fleet_ledger.tasks set lease_until = now() - interval '1 second' where id = %s",
                      (task_id,))
        admin.execute("select fleet_ledger.sweep_expired()")
        with seat.keep_alive(task, LEASE, FAST_BEAT) as beat:
            time.sleep(BEAT_WAIT_SECONDS)
        assert beat.lost and beat.renewals == 0


def test_wrong_password_is_refused_without_echoing_it(seat_credentials: SeatCredentials) -> None:
    wrong: str = secrets.token_urlsafe(24)
    bad = SeatCredentials(seat_credentials.login, SecretValue(wrong), seat_credentials.host,
                          seat_credentials.port, seat_credentials.dbname, TEST_SSLMODE)
    with pytest.raises(CredentialsError) as caught:
        SeatSession.from_credentials(bad)
    assert wrong not in str(caught.value)
