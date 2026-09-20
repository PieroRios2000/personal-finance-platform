"""The PR data diff reading two PostgreSQL databases (T29, ADR 0029): the
connection, the CLI and the per-schema rendering. Two small DuckDB files stand in
for the databases wherever the database itself is not what is under test."""

from pathlib import Path

import duckdb
import pytest

from scripts import data_diff


def _seed(path: Path, *statements: str) -> None:
    con = duckdb.connect(str(path))
    for statement in statements:
        con.execute(statement)
    con.close()


def test_the_postgres_attach_statement_quotes_the_password_and_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in {
        "PFP_PG_USER": "pfp",
        "PFP_PG_PASSWORD": "a'b c",
        "PFP_PG_DATABASE": "pfp",
    }.items():
        monkeypatch.setenv(name, value)

    statement = data_diff.postgres_attach("base", "pfp_diff_base")

    assert statement.startswith("ATTACH '")
    assert "dbname=pfp_diff_base" in statement
    assert statement.endswith("AS base (TYPE postgres, READ_ONLY)")
    assert "a'b c" not in statement  # escaped for both libpq and the SQL literal


def test_main_compares_two_postgres_databases_schema_by_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("base", "pr"):
        extra = ", (2)" if name == "pr" else ""
        _seed(
            tmp_path / f"{name}.duckdb",
            "CREATE SCHEMA silver",
            "CREATE SCHEMA gold",
            "CREATE TABLE silver.transactions (id INTEGER)",
            "INSERT INTO silver.transactions VALUES (1)",
            "CREATE TABLE gold.fact_transactions (id INTEGER)",
            f"INSERT INTO gold.fact_transactions VALUES (1){extra}",
        )
    monkeypatch.setattr(
        data_diff,
        "connect_postgres",
        lambda base, pr: data_diff.connect(
            tmp_path / "base.duckdb", tmp_path / "pr.duckdb"
        ),
    )

    code = data_diff.main(
        ["--base-database", "pfp_diff_base", "--pr-database", "pfp_diff_pr"]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "silver" in out and "gold" in out
    assert "fact_transactions" in out and "base 1 rows, PR 2 rows" in out


def test_a_schema_neither_side_has_is_left_out_not_reported_as_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("base", "pr"):
        _seed(
            tmp_path / f"{name}.duckdb",
            "CREATE SCHEMA silver",
            "CREATE TABLE silver.transactions (id INTEGER)",
        )

    code = data_diff.main(
        [
            "--base",
            str(tmp_path / "base.duckdb"),
            "--pr",
            str(tmp_path / "pr.duckdb"),
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "gold" not in out


def test_the_two_kinds_of_source_cannot_be_mixed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        data_diff.main(
            ["--base", str(tmp_path / "a.duckdb"), "--pr-database", "pfp_diff_pr"]
        )

    assert error.value.code == 2


def test_an_unreachable_postgres_is_exit_code_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(base: str, pr: str) -> duckdb.DuckDBPyConnection:
        raise duckdb.Error("connection refused")

    monkeypatch.setattr(data_diff, "connect_postgres", refuse)

    code = data_diff.main(["--base-database", "a", "--pr-database", "b"])

    assert code == 2
    assert "could not open" in capsys.readouterr().err
