"""Reading the manual Excel's `Ahorros` sheet into statements. Everything here
is invented; problems are reported as counts and row numbers, never values."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from ingestion.manual_excel import read_savings
from openpyxl import Workbook

from ingestion.reconciliation import reconcile
from ingestion.schema import hash_account
from scripts.make_manual_templates import SAVINGS_COLUMNS, write_template

_ACCOUNT = "Ahorros Prueba"


@pytest.fixture(autouse=True)
def account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")


def _workbook(path: Path, rows: list[tuple[Any, ...]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Ahorros"
    sheet.append(list(SAVINGS_COLUMNS))
    for row in rows:
        sheet.append(list(row))
    workbook.create_sheet("Inversiones").append(["lugar"])
    workbook.save(path)
    return path


def _row(day: date, description: str, amount: str, balance: str, currency: str = "PEN"):
    return (_ACCOUNT, day, description, float(amount), currency, float(balance))


_TWO_MONTHS = [
    _row(date(2026, 7, 5), "deposito", "100.00", "100.00"),
    _row(date(2026, 7, 20), "intereses", "1.50", "101.50"),
    _row(date(2026, 8, 10), "deposito", "50.00", "151.50"),
    _row(date(2026, 8, 31), "cierre de mes", "0", "151.50"),
]


def test_each_account_month_becomes_one_reconciled_statement(tmp_path: Path) -> None:
    result = read_savings(_workbook(tmp_path / "f.xlsx", _TWO_MONTHS), user_id="piero")

    assert result.problems == []
    july, august = (entry.statement for entry in result.entries)
    assert (july.period_start, july.period_end) == (date(2026, 7, 1), date(2026, 7, 31))
    assert (july.opening_balance, july.closing_balance) == (
        Decimal("0.00"),
        Decimal("101.50"),
    )
    assert (august.opening_balance, august.closing_balance) == (
        Decimal("101.50"),
        Decimal("151.50"),
    )
    for entry in result.entries:
        reconcile(entry.statement)
        assert entry.statement.account_kind == "asset"
        assert entry.statement.currency == "PEN"


def test_a_zero_amount_row_is_a_balance_marker_not_a_transaction(
    tmp_path: Path,
) -> None:
    result = read_savings(_workbook(tmp_path / "f.xlsx", _TWO_MONTHS), user_id="piero")

    august = result.entries[1].statement
    assert [t.amount for t in august.transactions] == [Decimal("50.00")]


def test_a_month_with_only_a_marker_is_a_statement_with_no_movements(
    tmp_path: Path,
) -> None:
    rows = [
        _row(date(2026, 7, 5), "deposito", "100.00", "100.00"),
        _row(date(2026, 8, 31), "cierre de mes", "0", "100.00"),
    ]

    result = read_savings(_workbook(tmp_path / "f.xlsx", rows), user_id="piero")

    august = result.entries[1].statement
    assert august.transactions == []
    assert august.opening_balance == august.closing_balance == Decimal("100.00")


def test_the_transactions_carry_the_month_identity_and_the_account(
    tmp_path: Path,
) -> None:
    result = read_savings(_workbook(tmp_path / "f.xlsx", _TWO_MONTHS), user_id="piero")

    entry = result.entries[0]
    assert entry.statement.account_id == hash_account(_ACCOUNT, _ACCOUNT)
    assert entry.statement.account_last4 == "0000"
    assert entry.statement.bank == _ACCOUNT
    assert all(
        t.source_file_sha256 == entry.file_sha256 for t in entry.statement.transactions
    )


def test_a_months_identity_does_not_depend_on_its_content(tmp_path: Path) -> None:
    """So that loading a corrected workbook replaces the month instead of
    adding a second one."""
    first = read_savings(_workbook(tmp_path / "a.xlsx", _TWO_MONTHS), user_id="piero")
    corrected = [
        _row(date(2026, 7, 5), "deposito", "100.00", "100.00"),
        _row(date(2026, 7, 21), "intereses", "2.00", "102.00"),
        *_TWO_MONTHS[2:],
    ]
    second = read_savings(_workbook(tmp_path / "b.xlsx", corrected), user_id="piero")

    assert [e.file_sha256 for e in first.entries][0] == second.entries[0].file_sha256
    assert first.entries[0].file_sha256 != first.entries[1].file_sha256


def test_currencies_of_one_account_are_separate_statements(tmp_path: Path) -> None:
    rows = [
        _row(date(2026, 7, 5), "deposito", "100.00", "100.00", "PEN"),
        _row(date(2026, 7, 6), "deposito", "10.00", "10.00", "USD"),
    ]

    result = read_savings(_workbook(tmp_path / "f.xlsx", rows), user_id="piero")

    assert {e.statement.currency for e in result.entries} == {"PEN", "USD"}
    assert len({e.file_sha256 for e in result.entries}) == 2


def test_a_balance_that_does_not_follow_is_a_problem_with_its_row_number(
    tmp_path: Path,
) -> None:
    rows = [
        _row(date(2026, 7, 5), "deposito", "100.00", "100.00"),
        _row(date(2026, 7, 20), "intereses", "1.50", "999.00"),
    ]

    result = read_savings(_workbook(tmp_path / "f.xlsx", rows), user_id="piero")

    assert result.entries == []
    assert result.problems == [
        "Ahorros row 3: the balance does not follow the previous one"
    ]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            (_ACCOUNT, "not a date", "x", 1.0, "PEN", 1.0),
            "Ahorros row 2: fecha is not a date",
        ),
        (
            (_ACCOUNT, date(2026, 7, 5), "x", "abc", "PEN", 1.0),
            "Ahorros row 2: monto is not a number",
        ),
        (
            (_ACCOUNT, date(2026, 7, 5), "x", 1.0, "EUR", 1.0),
            "Ahorros row 2: moneda must be PEN or USD",
        ),
        (
            (_ACCOUNT, date(2026, 7, 5), "x", 1.0, "PEN", None),
            "Ahorros row 2: saldo_final is not a number",
        ),
        (
            (None, date(2026, 7, 5), "x", 1.0, "PEN", 1.0),
            "Ahorros row 2: cuenta is empty",
        ),
        (
            (_ACCOUNT, date(2026, 7, 5), "", 1.0, "PEN", 1.0),
            "Ahorros row 2: descripcion is empty",
        ),
    ],
)
def test_invalid_cells_are_reported_by_row_and_column_never_by_value(
    tmp_path: Path, row: tuple[Any, ...], expected: str
) -> None:
    result = read_savings(_workbook(tmp_path / "f.xlsx", [row]), user_id="piero")

    assert result.entries == []
    assert expected in result.problems
    assert "abc" not in " ".join(result.problems)


def test_example_rows_left_in_the_sheet_are_a_problem(tmp_path: Path) -> None:
    template = tmp_path / "t.xlsx"
    write_template(template)

    result = read_savings(template, user_id="piero")

    assert result.entries == []
    assert result.problems == [
        "Ahorros: 3 example row(s) are still in the sheet (EJEMPLO)"
    ]


def test_empty_rows_are_ignored(tmp_path: Path) -> None:
    rows = [*_TWO_MONTHS, (None, None, None, None, None, None)]

    result = read_savings(_workbook(tmp_path / "f.xlsx", rows), user_id="piero")

    assert result.problems == []
    assert len(result.entries) == 2


def test_months_missing_between_the_first_and_last_are_counted(tmp_path: Path) -> None:
    rows = [
        _row(date(2026, 7, 5), "deposito", "100.00", "100.00"),
        _row(date(2026, 10, 5), "deposito", "50.00", "150.00"),
    ]

    result = read_savings(_workbook(tmp_path / "f.xlsx", rows), user_id="piero")

    assert result.missing_months == 2
    assert len(result.entries) == 2


def test_a_sheet_with_other_columns_is_a_clear_problem(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Ahorros"
    sheet.append(["cuenta", "fecha", "otra"])
    workbook.save(tmp_path / "f.xlsx")

    result = read_savings(tmp_path / "f.xlsx", user_id="piero")

    assert result.problems == ["Ahorros: the columns are not the template's"]


def test_a_workbook_without_the_sheet_is_a_clear_problem(tmp_path: Path) -> None:
    workbook = Workbook()
    workbook.save(tmp_path / "f.xlsx")

    assert read_savings(tmp_path / "f.xlsx", user_id="piero").problems == [
        "the workbook has no 'Ahorros' sheet"
    ]
