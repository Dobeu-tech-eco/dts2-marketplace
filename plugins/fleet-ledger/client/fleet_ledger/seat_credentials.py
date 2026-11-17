"""Everything a seat needs to open its own ledger connection."""
from __future__ import annotations

from dataclasses import dataclass

from .secret_value import SecretValue


@dataclass(frozen=True)
class SeatCredentials:
    """The password is a SecretValue, so printing or logging this object never shows it."""

    login: str
    password: SecretValue
    host: str
    port: int
    dbname: str
    sslmode: str
    sslrootcert: str | None = None
