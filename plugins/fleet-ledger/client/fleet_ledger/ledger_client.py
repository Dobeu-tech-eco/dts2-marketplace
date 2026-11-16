"""A small typed client for the fleet ledger seat functions (002-claims.sql).

It runs one SQL call per method and commits nothing itself: the caller owns the transaction,
so a claim is only visible to other seats once the caller commits.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from .claimed_task import ClaimedTask
from .db_connection import DbConnection
from .lease_lost_error import LEASE_LOST_SQLSTATE, LeaseLostError

DEFAULT_LEASE: Final[timedelta] = timedelta(hours=2)
Outcome = Literal["done", "parked"]

CLAIM_SQL: Final[str] = (
    "select task_id, lease_version, lease_until, title, done_when, risk_tier, roles_needed, roadmap_ref, body"
    " from fleet_ledger.claim_next(%s, %s::interval, %s)"
)
HEARTBEAT_SQL: Final[str] = "select fleet_ledger.heartbeat(%s, %s, %s::interval, %s)"
COMPLETE_SQL: Final[str] = "select fleet_ledger.complete(%s, %s, %s::jsonb, %s, %s)"
RELEASE_SQL: Final[str] = "select fleet_ledger.release(%s, %s, %s, %s)"


def _interval(lease: timedelta) -> str:
    return f"{int(lease.total_seconds())} seconds"


def _sqlstate(error: Exception) -> str | None:
    return getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)


class LedgerClient:
    """Seat-side calls. `seat_id` is only needed when the router acts for a seat; a seat login acts as itself."""

    def __init__(self, connection: DbConnection, seat_id: UUID | None = None) -> None:
        self._connection: Final[DbConnection] = connection
        self._seat: Final[str | None] = str(seat_id) if seat_id else None

    def claim_next(self, lease: timedelta = DEFAULT_LEASE, task_id: UUID | None = None) -> ClaimedTask | None:
        row: tuple[Any, ...] | None = self._fetch(CLAIM_SQL, (self._seat, _interval(lease), task_id and str(task_id)))
        if row is None:
            return None
        return ClaimedTask(
            task_id=UUID(str(row[0])), lease_version=row[1], lease_until=row[2], title=row[3], done_when=row[4],
            risk_tier=row[5], roles_needed=tuple(row[6] or ()), roadmap_ref=row[7], body=row[8] or {},
        )

    def heartbeat(self, task: ClaimedTask, lease: timedelta = DEFAULT_LEASE) -> datetime:
        row = self._fetch(HEARTBEAT_SQL, (str(task.task_id), task.lease_version, _interval(lease), self._seat))
        return row[0] if row else task.lease_until

    def complete(self, task: ClaimedTask, result: Mapping[str, Any], outcome: Outcome = "done") -> None:
        self._fetch(COMPLETE_SQL, (str(task.task_id), task.lease_version, json.dumps(dict(result)), outcome, self._seat))

    def release(self, task: ClaimedTask, reason: str | None = None) -> None:
        self._fetch(RELEASE_SQL, (str(task.task_id), task.lease_version, reason, self._seat))

    def _fetch(self, query: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        cursor = self._connection.cursor()
        try:
            cursor.execute(query, params)
            return cursor.fetchone()
        except Exception as error:
            if _sqlstate(error) == LEASE_LOST_SQLSTATE:
                raise LeaseLostError(str(error)) from error
            raise
        finally:
            cursor.close()
