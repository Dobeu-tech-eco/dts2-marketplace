"""Fixtures for the fleet ledger SQL tests.

The tests need a Postgres 15+ server where they may create databases and roles, given as
FLEET_LEDGER_TEST_DSN (for example postgresql://postgres@localhost:5432/postgres). They are
skipped when it is unset. pgmq is replaced by a stub, so a stock Postgres is enough.
"""
from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
SQL_DIR: Path = PLUGIN_ROOT / "sql"
DSN_VARIABLE: str = "FLEET_LEDGER_TEST_DSN"
PGMQ_LINE: str = "create extension if not exists pgmq;"
APP_ROLES: tuple[str, ...] = ("anon", "authenticated", "service_role")
PGMQ_STUB: str = """
create schema if not exists pgmq;
create or replace function pgmq.create(queue_name text) returns void language plpgsql as $$
begin
  execute format('create table pgmq.%I (msg_id bigint)', 'q_' || queue_name);
  execute format('create table pgmq.%I (msg_id bigint)', 'a_' || queue_name);
end;
$$;
"""

sys.path.insert(0, str(PLUGIN_ROOT / "client"))


def _admin_dsn() -> str:
    dsn: str | None = os.environ.get(DSN_VARIABLE)
    if not dsn:
        pytest.skip(f"{DSN_VARIABLE} is not set")
    return dsn


def _with_database(dsn: str, name: str) -> str:
    return psycopg.conninfo.make_conninfo(dsn, dbname=name)


def _foundation_sql() -> str:
    text: str = (SQL_DIR / "001-foundation.sql").read_text(encoding="utf-8")
    assert PGMQ_LINE in text, "001-foundation.sql changed: update the pgmq stub in conftest.py"
    return text.replace(PGMQ_LINE, "-- pgmq replaced by a stub for tests")


@pytest.fixture()
def ledger_dsn() -> Iterator[str]:
    """A fresh database with 001 and 002 applied. Yields its DSN and drops it afterwards."""
    admin: str = _admin_dsn()
    name: str = f"fleet_ledger_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'create database "{name}"')
        for role in APP_ROLES:
            conn.execute(
                f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}')"
                f" then create role {role} nologin; end if; end $$"
            )
    dsn: str = _with_database(admin, name)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("create extension if not exists pgcrypto")
            conn.execute(PGMQ_STUB)
            conn.execute(_foundation_sql())
            conn.execute((SQL_DIR / "002-claims.sql").read_text(encoding="utf-8"))
        yield dsn
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'drop database if exists "{name}" with (force)')
