"""Tests for the Scotiabank savings-account layout (`scotiabank.parse` falls
back to it when a PDF has no card header).

No real PDF is used (ADR 0004): every fixture is built by
`tests.fixtures.synthetic_pdfs.scotiabank_account_pdf`, calibrated against a
masked layout dump the owner reviewed himself.
"""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion.parsers import scotiabank
from ingestion.reconciliation import ReconciliationError
from ingestion.schema import Statement, hash_account
from tests.fixtures.synthetic_pdfs import Movement, scotiabank_account_pdf

FILE_SHA256 = hashlib.sha256(b"opaque id").hexdigest()


@pytest.fixture(autouse=True)
def account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")


def _parse(tmp_path: Path, data: bytes) -> list[Statement]:
    path = tmp_path / "account.pdf"
    path.write_bytes(data)
    return scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)


def test_a_savings_account_yields_one_reconciled_asset_statement(
    tmp_path: Path,
) -> None:
    (statement,) = _parse(tmp_path, scotiabank_account_pdf())

    assert statement.bank == "Scotiabank"
    assert statement.account_kind == "asset"
    assert statement.currency == "PEN"
    assert statement.opening_balance == Decimal("1000.00")
    # 1000.00 - 120.50 + 2500.00 - 85.30 + 300.00
    assert statement.closing_balance == Decimal("3594.20")
    assert len(statement.transactions) == 4


def test_cargo_is_negative_and_abono_positive(tmp_path: Path) -> None:
    (statement,) = _parse(tmp_path, scotiabank_account_pdf())

    by_description = {t.description: t.amount for t in statement.transactions}
    assert by_description["COMPRA TIENDA FICTICIA"] == Decimal("-120.50")
    assert by_description["DEPOSITO SUELDO FICTICIO"] == Decimal("2500.00")


def test_dates_take_their_year_from_the_period_and_use_the_value_date(
    tmp_path: Path,
) -> None:
    (statement,) = _parse(tmp_path, scotiabank_account_pdf())

    assert statement.period_start == date(2026, 1, 1)
    assert statement.period_end == date(2026, 1, 31)
    assert {t.date for t in statement.transactions} == {
        date(2026, 1, 5),
        date(2026, 1, 12),
        date(2026, 1, 20),
        date(2026, 1, 28),
    }


def test_a_period_across_new_year_puts_december_rows_in_the_earlier_year(
    tmp_path: Path,
) -> None:
    movements = (
        Movement(date(2025, 12, 30), "COMPRA DICIEMBRE FICTICIA", Decimal("-10.00")),
        Movement(date(2026, 1, 2), "COMPRA ENERO FICTICIA", Decimal("-5.00")),
    )
    data = scotiabank_account_pdf(
        movements=movements, period=(date(2025, 12, 26), date(2026, 1, 25))
    )

    (statement,) = _parse(tmp_path, data)

    assert sorted(t.date for t in statement.transactions) == [
        date(2025, 12, 30),
        date(2026, 1, 2),
    ]


def test_a_dollar_account_is_usd(tmp_path: Path) -> None:
    (statement,) = _parse(
        tmp_path, scotiabank_account_pdf(currency_words="M.E. DOLARES")
    )

    assert statement.currency == "USD"
    assert all(t.currency == "USD" for t in statement.transactions)


def test_the_account_is_identified_by_its_number(tmp_path: Path) -> None:
    (statement,) = _parse(tmp_path, scotiabank_account_pdf())

    assert statement.account_last4 == "0000"
    assert statement.account_id == hash_account("Scotiabank", "000-0000000")


def test_a_closing_balance_that_does_not_match_the_movements_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(ReconciliationError):
        _parse(tmp_path, scotiabank_account_pdf(reconciles=False))


def test_a_layout_with_neither_header_is_still_reported_cleanly(
    tmp_path: Path,
) -> None:
    from fpdf import FPDF

    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(40, 40, "nothing recognizable here")

    with pytest.raises(ValueError, match="could not find"):
        _parse(tmp_path, bytes(pdf.output()))
