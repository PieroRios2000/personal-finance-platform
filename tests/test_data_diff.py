"""Tests for scripts.data_diff: base-vs-PR silver comparison (T17b).

Two small DuckDB files built by hand for every test -- never the real pipeline --
so the diff logic itself is fast and unit-testable in isolation, per T17b's own
acceptance criteria (tasks/todo.md). `data_diff.connect()` attaches both
read-only into one in-memory connection (`base` and `pr`), so every comparison
below is a single-connection query, the same shape `dbt build` output gets
compared in CI.
"""

from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from scripts import data_diff


def _seed(path: Path, *statements: str) -> None:
    """Runs `CREATE SCHEMA silver` plus whatever DDL/DML `statements` says,
    against a fresh on-disk DuckDB file at `path`."""
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA silver")
    for statement in statements:
        con.execute(statement)
    con.close()


@pytest.fixture
def base_db(tmp_path: Path) -> Path:
    return tmp_path / "base.duckdb"


@pytest.fixture
def pr_db(tmp_path: Path) -> Path:
    return tmp_path / "pr.duckdb"


def test_diff_columns_reports_added_removed_and_type_changed() -> None:
    base_cols = {"id": "INTEGER", "amount": "DECIMAL(18,2)"}
    pr_cols = {"id": "BIGINT", "amount": "DECIMAL(18,2)", "currency": "VARCHAR"}

    diff = data_diff.diff_columns(base_cols, pr_cols)

    assert diff.added == ("currency",)
    assert diff.removed == ()
    assert diff.type_changed == (("id", "INTEGER", "BIGINT"),)
    assert diff.is_empty is False


def test_diff_columns_is_empty_when_columns_match() -> None:
    cols = {"id": "INTEGER", "amount": "DECIMAL(18,2)"}

    assert data_diff.diff_columns(cols, dict(cols)).is_empty is True


def test_same_schema_different_rows_are_sampled_both_ways(
    base_db: Path, pr_db: Path
) -> None:
    _seed(
        base_db,
        "CREATE TABLE silver.transactions (id INTEGER, amount DECIMAL(18,2))",
        "INSERT INTO silver.transactions VALUES (1, 10.00), (2, 20.00)",
    )
    _seed(
        pr_db,
        "CREATE TABLE silver.transactions (id INTEGER, amount DECIMAL(18,2))",
        "INSERT INTO silver.transactions VALUES (1, 10.00), (2, 99.00)",
    )

    con = data_diff.connect(base_db, pr_db)
    [transactions] = data_diff.diff_all(con)

    assert transactions.name == "transactions"
    assert transactions.base_rows == 2
    assert transactions.pr_rows == 2
    assert transactions.columns.is_empty
    assert transactions.has_changes is True
    assert transactions.sample_only_in_base == ((2, Decimal("20.00")),)
    assert transactions.sample_only_in_pr == ((2, Decimal("99.00")),)


def test_a_column_added_in_the_pr_is_reported(base_db: Path, pr_db: Path) -> None:
    _seed(
        base_db,
        "CREATE TABLE silver.transactions (id INTEGER, amount DECIMAL(18,2))",
        "INSERT INTO silver.transactions VALUES (1, 10.00)",
    )
    _seed(
        pr_db,
        "CREATE TABLE silver.transactions "
        "(id INTEGER, amount DECIMAL(18,2), currency VARCHAR)",
        "INSERT INTO silver.transactions VALUES (1, 10.00, 'PEN')",
    )

    con = data_diff.connect(base_db, pr_db)
    [transactions] = data_diff.diff_all(con)

    assert transactions.columns.added == ("currency",)
    assert transactions.columns.removed == ()
    assert transactions.has_changes is True


def test_a_model_missing_from_the_pr_is_reported_not_crashed(
    base_db: Path, pr_db: Path
) -> None:
    _seed(
        base_db,
        "CREATE TABLE silver.transactions (id INTEGER)",
        "INSERT INTO silver.transactions VALUES (1)",
        "CREATE TABLE silver.statements (id INTEGER)",
        "INSERT INTO silver.statements VALUES (1)",
    )
    _seed(
        pr_db,
        "CREATE TABLE silver.transactions (id INTEGER)",
        "INSERT INTO silver.transactions VALUES (1)",
    )

    con = data_diff.connect(base_db, pr_db)
    diffs = {d.name: d for d in data_diff.diff_all(con)}

    assert diffs["transactions"].has_changes is False
    statements = diffs["statements"]
    assert statements.base_rows == 1
    assert statements.pr_rows is None
    assert statements.has_changes is True


def test_a_model_new_in_the_pr_is_reported_not_crashed(
    base_db: Path, pr_db: Path
) -> None:
    _seed(
        base_db,
        "CREATE TABLE silver.transactions (id INTEGER)",
        "INSERT INTO silver.transactions VALUES (1)",
    )
    _seed(
        pr_db,
        "CREATE TABLE silver.transactions (id INTEGER)",
        "INSERT INTO silver.transactions VALUES (1)",
        "CREATE TABLE silver.statements (id INTEGER)",
        "INSERT INTO silver.statements VALUES (1)",
    )

    con = data_diff.connect(base_db, pr_db)
    diffs = {d.name: d for d in data_diff.diff_all(con)}

    statements = diffs["statements"]
    assert statements.base_rows is None
    assert statements.pr_rows == 1
    assert statements.has_changes is True


def test_identical_databases_report_no_changes(base_db: Path, pr_db: Path) -> None:
    for path in (base_db, pr_db):
        _seed(
            path,
            "CREATE TABLE silver.transactions (id INTEGER, amount DECIMAL(18,2))",
            "INSERT INTO silver.transactions VALUES (1, 10.00), (2, 20.00)",
        )

    con = data_diff.connect(base_db, pr_db)
    diffs = data_diff.diff_all(con)

    assert all(not d.has_changes for d in diffs)
    assert "no changes" in data_diff.render_markdown(diffs).lower()


def test_render_markdown_reports_a_real_difference(base_db: Path, pr_db: Path) -> None:
    _seed(
        base_db,
        "CREATE TABLE silver.transactions (id INTEGER)",
        "INSERT INTO silver.transactions VALUES (1), (2)",
    )
    _seed(
        pr_db,
        "CREATE TABLE silver.transactions (id INTEGER)",
        "INSERT INTO silver.transactions VALUES (1), (2), (3)",
    )

    con = data_diff.connect(base_db, pr_db)
    markdown = data_diff.render_markdown(data_diff.diff_all(con))

    assert "transactions" in markdown
    assert "2" in markdown
    assert "3" in markdown
    assert "no changes" not in markdown.lower()


def test_the_differing_row_sample_is_bounded(base_db: Path, pr_db: Path) -> None:
    _seed(
        base_db,
        "CREATE TABLE silver.transactions (id INTEGER)",
        "INSERT INTO silver.transactions SELECT * FROM range(10)",
    )
    _seed(pr_db, "CREATE TABLE silver.transactions (id INTEGER)")

    con = data_diff.connect(base_db, pr_db)
    [transactions] = data_diff.diff_all(con, sample_limit=3)

    assert len(transactions.sample_only_in_base) == 3


def test_main_prints_markdown_to_stdout_and_returns_zero(
    base_db: Path, pr_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for path in (base_db, pr_db):
        _seed(
            path,
            "CREATE TABLE silver.transactions (id INTEGER)",
            "INSERT INTO silver.transactions VALUES (1)",
        )

    exit_code = data_diff.main(["--base", str(base_db), "--pr", str(pr_db)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "no changes" in out.lower()


def test_main_fails_loudly_on_a_missing_file(pr_db: Path, tmp_path: Path) -> None:
    _seed(pr_db, "CREATE TABLE silver.transactions (id INTEGER)")

    exit_code = data_diff.main(
        ["--base", str(tmp_path / "does-not-exist.duckdb"), "--pr", str(pr_db)]
    )

    assert exit_code == 2
