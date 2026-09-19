"""dbt builds silver and gold into PostgreSQL through DuckDB's attach (T26, ADR 0029).

Each test gets its own throwaway database (`pfp_test_<worker>`) on the Postgres
that `make pg-up` starts, so the owner's real `silver`/`gold` are never touched;
the lake is the same wiped, per-worker test lake every dbt integration file uses.
Needs the PFP_PG_* variables (see `.env.example`) and a running Postgres.
Deselected by default; run with `pytest -m integration`.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from tests.test_dbt_gold_integration import lake as _lake
from tests.test_dbt_silver_integration import _FEBRUARY, _JANUARY, _REPO_ROOT, _write

pytestmark = pytest.mark.integration

lake = _lake

_REQUIRED = (
    "PFP_PG_HOST",
    "PFP_PG_PORT",
    "PFP_PG_DATABASE",
    "PFP_PG_USER",
    "PFP_PG_PASSWORD",
    "PFP_PG_BI_PASSWORD",
)
_GRANTS = Path(__file__).resolve().parent.parent / "postgres" / "grants.sql"


def _redacted(result: subprocess.CompletedProcess[str]) -> str:
    """dbt's output for an assertion message, without the Postgres password."""
    output = result.stdout
    for name in ("PFP_PG_PASSWORD", "PFP_PG_BI_PASSWORD"):
        output = output.replace(os.environ[name], "***")
    return output


def _conninfo(
    database: str, user: str | None = None, password: str | None = None
) -> str:
    return (
        f"host={os.environ['PFP_PG_HOST']} port={os.environ['PFP_PG_PORT']} "
        f"dbname={database} user={user or os.environ['PFP_PG_USER']} "
        f"password={password or os.environ['PFP_PG_PASSWORD']}"
    )


@pytest.fixture
def database() -> Iterator[str]:
    missing = [name for name in _REQUIRED if not os.environ.get(name)]
    if missing:
        pytest.skip(f"missing env var(s): {', '.join(missing)} (see .env.example)")

    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    name = f"pfp_test_{worker}"
    admin = psycopg.connect(_conninfo(os.environ["PFP_PG_DATABASE"]), autocommit=True)
    try:
        admin.execute(f'drop database if exists "{name}" with (force)')
        admin.execute(f'create database "{name}"')
        yield name
    finally:
        admin.execute(f'drop database if exists "{name}" with (force)')
        admin.close()


def _dbt_build(tmp_path: Path, database: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "PFP_PG_DATABASE": database,
        "PFP_ELEMENTARY_DUCKDB_PATH": str(tmp_path / "elementary.duckdb"),
    }
    return subprocess.run(
        [
            str(Path(sys.executable).parent / "dbt"),
            "build",
            "--project-dir",
            "dbt",
            "--profiles-dir",
            "dbt",
            "--target",
            "postgres",
            "--target-path",
            str(tmp_path / "target"),
            "--log-path",
            str(tmp_path / "logs"),
        ],
        cwd=_REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _scalar(database: str, query: str) -> object:
    with psycopg.connect(_conninfo(database)) as connection:
        row = connection.execute(query).fetchone()
    assert row is not None
    return row[0]


def _tables(database: str) -> set[str]:
    with psycopg.connect(_conninfo(database)) as connection:
        rows = connection.execute(
            "select table_schema || '.' || table_name from information_schema.tables "
            "where table_schema not in ('pg_catalog', 'information_schema')"
        ).fetchall()
    return {row[0] for row in rows}


def _seed() -> None:
    _write(*_JANUARY)
    _write(*_FEBRUARY)


def test_silver_and_gold_are_built_in_postgres_and_elementary_is_not(
    lake: str, database: str, tmp_path: Path
) -> None:
    _seed()

    result = _dbt_build(tmp_path, database)

    assert result.returncode == 0, _redacted(result)
    tables = _tables(database)
    assert {"silver.transactions", "gold.fact_transactions", "gold.dim_bank"} <= tables
    assert not any(t.startswith("elementary.") for t in tables)
    assert (tmp_path / "elementary.duckdb").exists()
    assert _scalar(database, "select count(*) from gold.fact_transactions") == 2


def test_a_second_build_changes_nothing_in_postgres(
    lake: str, database: str, tmp_path: Path
) -> None:
    _seed()
    assert _dbt_build(tmp_path, database).returncode == 0
    first = _scalar(database, "select count(*) from silver.transactions")

    second = _dbt_build(tmp_path, database)

    assert second.returncode == 0, _redacted(second)
    assert _scalar(database, "select count(*) from silver.transactions") == first == 2


def test_the_bi_role_reads_gold_only_and_keeps_doing_so_after_a_rebuild(
    lake: str, database: str, tmp_path: Path
) -> None:
    """The real `postgres/grants.sql` (the file the container's init script runs)
    applied to the throwaway database, then a rebuild: dbt drops and recreates
    tables, so the read-only role's privilege has to follow the new ones. The
    cluster-level role comes from `init-roles.sh` when the Postgres volume is
    first created; a volume made before T26 does not have it (`make poc-down`,
    then `make pg-up`), and a BI password changed in `.env` afterwards no longer
    matches."""
    _seed()
    assert _dbt_build(tmp_path, database).returncode == 0
    owner = os.environ["PFP_PG_USER"]
    grants = _GRANTS.read_text().replace(':"owner"', f'"{owner}"')
    grants = grants.replace(':"database"', f'"{database}"')
    with psycopg.connect(_conninfo(database), autocommit=True) as admin:
        for statement in grants.split(";"):
            if statement.strip():
                admin.execute(statement)
    assert _dbt_build(tmp_path, database).returncode == 0  # recreates the tables

    bi_password = os.environ["PFP_PG_BI_PASSWORD"]
    with psycopg.connect(_conninfo(database, "pfp_bi", bi_password)) as reader:
        assert reader.execute(
            "select count(*) from gold.fact_transactions"
        ).fetchone() == (2,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("select count(*) from silver.transactions")
        reader.rollback()
        # Read-only sessions: a write fails before privileges are checked.
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            reader.execute("create table gold.not_allowed (a int)")
        reader.rollback()
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            reader.execute("create temp table not_allowed (a int)")
