"""Renews a claimed task's lease in the background while the seat works on it.

Use it as a context manager. It renews every `interval` (default: a third of the lease). It marks the
task `lost` for good when the ledger says the lease is lost, or when no renewal has succeeded for a whole
lease (the server will have taken the task back by then). Check `lost` before committing any result.
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta
from types import TracebackType
from typing import Final, Self

from .claimed_task import ClaimedTask
from .lease_lost_error import LeaseLostError
from .ledger_client import DEFAULT_LEASE, LedgerClient

RENEWALS_PER_LEASE: Final[int] = 3
DEFAULT_STOP_TIMEOUT: Final[timedelta] = timedelta(seconds=30)


class HeartbeatKeeper:
    """`lock` must be the same lock that guards every other use of the client's connection."""

    def __init__(self, client: LedgerClient, task: ClaimedTask, lock: threading.Lock,
                 lease: timedelta = DEFAULT_LEASE, interval: timedelta | None = None,
                 stop_timeout: timedelta = DEFAULT_STOP_TIMEOUT) -> None:
        self._client: Final[LedgerClient] = client
        self._task: Final[ClaimedTask] = task
        self._lock: Final[threading.Lock] = lock
        self._lease: Final[timedelta] = lease
        self._interval: Final[float] = (interval or lease / RENEWALS_PER_LEASE).total_seconds()
        self._stop_timeout: Final[float] = stop_timeout.total_seconds()
        self._stop: Final[threading.Event] = threading.Event()
        self._lost: Final[threading.Event] = threading.Event()
        self._thread: Final[threading.Thread] = threading.Thread(target=self._run, name="fleet-ledger-heartbeat",
                                                                 daemon=True)
        self._last_ok: float = time.monotonic()
        self.renewals: int = 0
        self.failures: int = 0
        self.last_error: str | None = None

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    @property
    def stopped(self) -> bool:
        return not self._thread.is_alive()

    def __enter__(self) -> Self:
        self._last_ok = time.monotonic()
        self._thread.start()
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 trace: TracebackType | None) -> None:
        self._stop.set()
        self._thread.join(self._stop_timeout)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            if not self._renew():
                return

    def _renew(self) -> bool:
        try:
            with self._lock:
                self._client.heartbeat(self._task, self._lease)
        except LeaseLostError:
            self._lost.set()
            return False
        except Exception as error:  # noqa: BLE001 -- transient failure: retry until a whole lease passes
            return self._note_failure(type(error).__name__)
        self._last_ok = time.monotonic()
        self.renewals += 1
        return True

    def _note_failure(self, name: str) -> bool:
        self.failures += 1
        self.last_error = name
        if time.monotonic() - self._last_ok >= self._lease.total_seconds():
            self._lost.set()
            return False
        return True
