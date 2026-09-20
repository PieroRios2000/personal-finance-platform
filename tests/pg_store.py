"""Reading what dbt built in PostgreSQL, for the dbt integration tests (T27, ADR 0029).

Each pytest-xdist worker has its own throwaway database (`pfp_test_<worker>`) on the
Postgres that `make pg-up` starts, dropped and recreated with the test lake
(`tests/test_dbt_silver_integration.py::_wipe_test_lake`), so parallel tests never
share tables and the owner's real `pfp` database is never touched.

`connect()` returns a connection whose `execute()` accepts the DuckDB-style `?`
placeholders the tests were written with.
"""

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg

REQUIRED_ENV = (
    "PFP_PG_HOST",
    "PFP_PG_PORT",
    "PFP_PG_DATABASE",
    "PFP_PG_USER",
    "PFP_PG_PASSWORD",
)


def missing_env() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def worker_database() -> str:
    return f"pfp_test_{os.environ.get('PYTEST_XDIST_WORKER', 'main')}"


def _conninfo(database: str) -> str:
    return (
        f"host={os.environ['PFP_PG_HOST']} port={os.environ['PFP_PG_PORT']} "
        f"dbname={database} user={os.environ['PFP_PG_USER']} "
        f"password={os.environ['PFP_PG_PASSWORD']}"
    )


def translate_placeholders(sql: str, params: Sequence[Any] | None) -> str:
    """DuckDB's `?` to psycopg's `%s`; a literal `%` is doubled when there are
    parameters (psycopg would read it as a placeholder)."""
    if params is None:
        return sql
    return sql.replace("%", "%%").replace("?", "%s")


class _Connection:
    def __init__(self, connection: "psycopg.Connection[Any]") -> None:
        self._connection = connection

    def execute(
        self, sql: str, params: Sequence[Any] | None = None
    ) -> "psycopg.Cursor[Any]":
        return self._connection.execute(translate_placeholders(sql, params), params)


@contextmanager
def connect() -> Iterator[_Connection]:
    """A read connection to this worker's database."""
    with psycopg.connect(_conninfo(worker_database())) as connection:
        yield _Connection(connection)


def reset_database() -> None:
    """Drop and recreate this worker's database (empty, no schemas)."""
    name = worker_database()
    with psycopg.connect(
        _conninfo(os.environ["PFP_PG_DATABASE"]), autocommit=True
    ) as admin:
        admin.execute(f'drop database if exists "{name}" with (force)')
        admin.execute(f'create database "{name}"')


def drop_database() -> None:
    with psycopg.connect(
        _conninfo(os.environ["PFP_PG_DATABASE"]), autocommit=True
    ) as admin:
        admin.execute(f'drop database if exists "{worker_database()}" with (force)')


def dbt_environment(tmp_path: Path) -> dict[str, str]:
    """The environment for a `dbt build` in a test: this worker's database, and an
    Elementary DuckDB file of its own (ADR 0029)."""
    return {
        **os.environ,
        "PFP_PG_DATABASE": worker_database(),
        "PFP_ELEMENTARY_DUCKDB_PATH": str(tmp_path / "elementary.duckdb"),
    }
