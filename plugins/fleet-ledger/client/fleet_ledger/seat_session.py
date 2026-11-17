"""What a seat runs: its own login, one autocommit connection, and the four ledger calls behind one lock.

    with SeatSession.from_doppler() as seat:
        task = seat.claim()
        if task:
            with seat.keep_alive(task) as beat:
                result = do_the_work(task)
            if not beat.lost:
                seat.complete(task, result)
"""
from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import timedelta
from types import TracebackType
from typing import Any, Final, Self

from .claimed_task import ClaimedTask
from .doppler_source import load_seat_credentials
from .heartbeat_keeper import HeartbeatKeeper
from .ledger_client import DEFAULT_LEASE, LedgerClient, Outcome
from .seat_connection import connect_seat
from .seat_credentials import SeatCredentials

CLOSE_WAIT_SECONDS: Final[float] = 30.0


class SeatSession:
    """A seat login always acts as itself, so no seat id is passed to the ledger."""

    def __init__(self, connection: Any) -> None:
        self._connection: Final[Any] = connection
        self._lock: Final[threading.Lock] = threading.Lock()
        self._client: Final[LedgerClient] = LedgerClient(connection)

    @classmethod
    def from_credentials(cls, credentials: SeatCredentials) -> SeatSession:
        return cls(connect_seat(credentials))

    @classmethod
    def from_doppler(cls) -> SeatSession:
        return cls.from_credentials(load_seat_credentials())

    @property
    def connection(self) -> Any:
        return self._connection

    def claim(self, lease: timedelta = DEFAULT_LEASE) -> ClaimedTask | None:
        with self._lock:
            return self._client.claim_next(lease)

    def keep_alive(self, task: ClaimedTask, lease: timedelta = DEFAULT_LEASE,
                   interval: timedelta | None = None) -> HeartbeatKeeper:
        return HeartbeatKeeper(self._client, task, self._lock, lease, interval)

    def complete(self, task: ClaimedTask, result: Mapping[str, Any], outcome: Outcome = "done") -> None:
        with self._lock:
            self._client.complete(task, result, outcome)

    def release(self, task: ClaimedTask, reason: str | None = None) -> None:
        with self._lock:
            self._client.release(task, reason)

    def close(self) -> None:
        """Waits a bounded time for a running call; closes the connection either way."""
        acquired: bool = self._lock.acquire(timeout=CLOSE_WAIT_SECONDS)
        try:
            self._connection.close()
        finally:
            if acquired:
                self._lock.release()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 trace: TracebackType | None) -> None:
        self.close()
