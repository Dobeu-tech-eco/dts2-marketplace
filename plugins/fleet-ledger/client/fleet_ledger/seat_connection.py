"""Opens a seat's own ledger connection with psycopg 3.

The connection is in autocommit mode, so every seat call commits at once. That matters: a claim holds
the event-chain lock until its transaction ends, so a seat must never keep one open. TCP keepalives and a
user timeout make a dead network fail fast instead of hanging a heartbeat.

The password goes to the driver as a keyword argument and nowhere else. On failure only the SQLSTATE or
the error's class name is reported, and the error is raised outside the `except` block, so no exception
chain keeps the driver's frames (which hold the password) alive.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from .credentials_error import CredentialsError
from .seat_credentials import SeatCredentials

APPLICATION_NAME: Final[str] = "fleet-ledger-seat"
CONNECT_TIMEOUT_SECONDS: Final[int] = 10
KEEPALIVE_IDLE_SECONDS: Final[int] = 30
KEEPALIVE_INTERVAL_SECONDS: Final[int] = 10
KEEPALIVE_COUNT: Final[int] = 3
TCP_USER_TIMEOUT_MS: Final[int] = 30_000

Connector = Callable[..., Any]


def _default_connector() -> Connector:
    import psycopg  # imported here so the rest of the client works without psycopg installed

    return psycopg.connect


def _options(credentials: SeatCredentials) -> dict[str, Any]:
    options: dict[str, Any] = {
        "host": credentials.host, "port": credentials.port, "dbname": credentials.dbname,
        "user": credentials.login, "sslmode": credentials.sslmode, "application_name": APPLICATION_NAME,
        "connect_timeout": CONNECT_TIMEOUT_SECONDS, "keepalives": 1, "keepalives_idle": KEEPALIVE_IDLE_SECONDS,
        "keepalives_interval": KEEPALIVE_INTERVAL_SECONDS, "keepalives_count": KEEPALIVE_COUNT,
        "tcp_user_timeout": TCP_USER_TIMEOUT_MS, "autocommit": True,
    }
    if credentials.sslrootcert:
        options["sslrootcert"] = credentials.sslrootcert
    return options


def connect_seat(credentials: SeatCredentials, connector: Connector | None = None) -> Any:
    """Returns an autocommit connection logged in as the seat. Raises CredentialsError on refusal."""
    connect: Connector = connector or _default_connector()
    reason: str | None = None
    try:
        return connect(password=credentials.password.reveal(), **_options(credentials))
    except Exception as error:  # noqa: BLE001 -- any driver error becomes a CredentialsError with no message text
        reason = str(getattr(error, "sqlstate", None) or type(error).__name__)
    raise CredentialsError(f"could not connect as {credentials.login} ({reason})")
