"""The slice of a DB-API 2.0 connection the client needs (psycopg 3 and psycopg2 both fit)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol


class DbCursor(Protocol):
    def execute(self, query: str, params: Sequence[Any] = ...) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...


class DbConnection(Protocol):
    def cursor(self) -> Any: ...
