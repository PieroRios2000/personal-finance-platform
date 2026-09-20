"""The shared helper the dbt integration tests use to read what dbt built in
PostgreSQL (T27, ADR 0029). The parts that need no database."""

from pathlib import Path

import pytest

from tests.pg_store import (
    dbt_environment,
    missing_env,
    translate_placeholders,
    worker_database,
)


def test_a_test_database_is_named_after_its_xdist_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")

    assert worker_database() == "pfp_test_gw3"


def test_without_xdist_the_test_database_is_the_main_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    assert worker_database() == "pfp_test_main"


def test_duckdb_style_question_marks_become_psycopg_placeholders() -> None:
    assert (
        translate_placeholders("where a = ? and b = ?", ("x", "y"))
        == "where a = %s and b = %s"
    )


def test_a_query_without_parameters_is_left_alone() -> None:
    assert translate_placeholders("select '50%' as pct", None) == "select '50%' as pct"


def test_a_percent_sign_in_a_query_with_parameters_is_escaped() -> None:
    assert (
        translate_placeholders("where d like 'A%' and x = ?", ("y",))
        == "where d like 'A%%' and x = %s"
    )


def test_dbt_runs_against_the_workers_database_and_a_private_elementary_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")

    environment = dbt_environment(tmp_path)

    assert environment["PFP_PG_DATABASE"] == "pfp_test_gw1"
    assert environment["PFP_ELEMENTARY_DUCKDB_PATH"] == str(
        tmp_path / "elementary.duckdb"
    )


def test_the_missing_postgres_variables_are_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PFP_PG_HOST", "PFP_PG_PORT", "PFP_PG_DATABASE", "PFP_PG_USER"):
        monkeypatch.setenv(name, "x")
    monkeypatch.delenv("PFP_PG_PASSWORD", raising=False)

    assert missing_env() == ["PFP_PG_PASSWORD"]
