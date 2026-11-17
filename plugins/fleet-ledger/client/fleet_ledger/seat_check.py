"""Checks that a seat login has exactly the rights it should. Claims no real work. Like any claim call,
the first check may return lapsed leases to the queue, which the ledger does on every claim anyway.

1. autocommit         the connection commits every call, so no claim holds the event-chain lock
2. rights_scoped      the login is in fleet_seat, is not a superuser, cannot bypass RLS and cannot sweep
3. claim_ok           claim_next runs (asked for a task id that cannot exist, so nothing is taken)
4. tables_denied      reading a ledger table directly is refused
5. other_seat_denied  acting for another seat is refused
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from .ledger_client import LedgerClient

PERMISSION_DENIED: Final[str] = "42501"
RIGHTS_SQL: Final[str] = (
    "select r.rolsuper, r.rolbypassrls, pg_has_role(current_user, 'fleet_seat', 'MEMBER'),"
    " has_function_privilege('fleet_ledger.sweep_expired()', 'EXECUTE')"
    " from pg_catalog.pg_roles r where r.rolname = current_user"
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def _sqlstate(error: Exception) -> str:
    return str(getattr(error, "sqlstate", None) or getattr(error, "pgcode", None) or type(error).__name__)


def _expect_success(name: str, action: Callable[[], Any]) -> CheckResult:
    try:
        outcome: Any = action()
    except Exception as error:  # noqa: BLE001 -- any failure is a failed check, reported by SQLSTATE
        return CheckResult(name, False, f"failed with {_sqlstate(error)}")
    return CheckResult(name, outcome is None, "ran, nothing claimed" if outcome is None else "claimed a task")


def _expect_denied(name: str, action: Callable[[], Any]) -> CheckResult:
    try:
        action()
    except Exception as error:  # noqa: BLE001 -- the refusal is what the check expects
        state: str = _sqlstate(error)
        return CheckResult(name, state == PERMISSION_DENIED, f"refused with {state}")
    return CheckResult(name, False, "was allowed")


def _autocommit(connection: Any) -> CheckResult:
    on: bool = bool(getattr(connection, "autocommit", False))
    return CheckResult("autocommit", on, "on" if on else "off: every claim would hold the event-chain lock")


def _rights(connection: Any) -> CheckResult:
    cursor = connection.cursor()
    try:
        cursor.execute(RIGHTS_SQL)
        row: tuple[Any, ...] | None = cursor.fetchone()
    except Exception as error:  # noqa: BLE001 -- any failure is a failed check, reported by SQLSTATE
        return CheckResult("rights_scoped", False, f"failed with {_sqlstate(error)}")
    finally:
        cursor.close()
    if row is None:
        return CheckResult("rights_scoped", False, "login not found")
    problems: list[str] = [label for label, bad in (
        ("superuser", row[0]), ("bypasses RLS", row[1]), ("not in fleet_seat", not row[2]),
        ("can run sweep_expired", row[3])) if bad]
    return CheckResult("rights_scoped", not problems, ", ".join(problems) or "only the fleet_seat group")


def _read_tasks(connection: Any) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("select 1 from fleet_ledger.tasks limit 1")
    finally:
        cursor.close()


def run_seat_check(connection: Any) -> list[CheckResult]:
    """`connection` must be an autocommit connection logged in as the seat."""
    own: LedgerClient = LedgerClient(connection)
    other: LedgerClient = LedgerClient(connection, seat_id=uuid.uuid4())
    return [
        _autocommit(connection),
        _rights(connection),
        _expect_success("claim_ok", lambda: own.claim_next(task_id=uuid.uuid4())),
        _expect_denied("tables_denied", lambda: _read_tasks(connection)),
        _expect_denied("other_seat_denied", lambda: other.claim_next(task_id=uuid.uuid4())),
    ]
