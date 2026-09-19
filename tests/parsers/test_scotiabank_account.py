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
from typing import Any

import pytest

from ingestion.parsers import scotiabank, scotiabank_account
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


def _pages(**fixture_args: Any) -> list[list[list[dict[str, Any]]]]:
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(scotiabank_account_pdf(**fixture_args))) as doc:
        return [scotiabank._group_lines(p.extract_words()) for p in doc.pages]


def _without(pages: list[list[list[dict[str, Any]]]], word: str) -> Any:
    return [
        [ln for ln in page if word not in {w["text"] for w in ln}] for page in pages
    ]


def _parse_pages(pages: Any) -> Any:
    return scotiabank_account.parse_pages(
        pages, user_id="piero", file_sha256=FILE_SHA256
    )


def test_a_row_outside_the_period_is_rejected(tmp_path: Path) -> None:
    data = scotiabank_account_pdf(
        movements=(Movement(date(2026, 3, 5), "FUERA DE PERIODO", Decimal("-1.00")),)
    )

    with pytest.raises(ValueError, match="outside the statement period"):
        _parse(tmp_path, data)


def test_feb_29_is_read_in_the_leap_year_of_the_period(tmp_path: Path) -> None:
    data = scotiabank_account_pdf(
        movements=(Movement(date(2028, 2, 29), "BISIESTO FICTICIO", Decimal("-1.00")),),
        period=(date(2027, 12, 20), date(2028, 3, 1)),
    )

    (statement,) = _parse(tmp_path, data)

    assert statement.transactions[0].date == date(2028, 2, 29)


def test_september_is_read_as_set_or_sep() -> None:
    assert scotiabank_account._month("SET") == scotiabank_account._month("sep") == 9


def test_an_unknown_month_is_rejected() -> None:
    with pytest.raises(ValueError, match="unrecognized month"):
        scotiabank_account._month("XYZ")


def test_a_row_with_both_cargo_and_abono_is_rejected() -> None:
    pages = _pages()
    row = next(ln for ln in pages[0] if ln[0]["text"] == "05/01")
    # give the first row a second movement amount under ABONO
    header = next(ln for ln in pages[0] if "ABONO" in {w["text"] for w in ln})
    abono_x1 = next(w["x1"] for w in header if w["text"] == "ABONO") + 12
    row.append(
        {"text": "9.99", "x0": abono_x1 - 20, "x1": abono_x1, "top": row[0]["top"]}
    )

    with pytest.raises(ValueError, match="exactly one CARGO or ABONO"):
        _parse_pages(pages)


def test_a_statement_without_an_account_line_is_rejected() -> None:
    with pytest.raises(ValueError, match="could not find the account number"):
        _parse_pages(_without(_pages(), "CUENTA"))


def test_a_statement_without_its_saldo_final_lines_is_rejected() -> None:
    with pytest.raises(ValueError, match="'Saldo Final'"):
        _parse_pages(_without(_pages(), "Saldo"))


def test_a_closing_line_without_totals_is_rejected() -> None:
    pages = _pages()
    closing = [ln for ln in pages[0] if "Saldo" in {w["text"] for w in ln}][-1]
    closing[:] = [w for w in closing if w["x1"] > 560 or not w["text"][0].isdigit()]

    with pytest.raises(ValueError, match="has no totals"):
        _parse_pages(pages)


def test_a_dollar_account_written_with_an_accent_is_usd() -> None:
    pages = _pages()
    for page in pages:
        for line in page:
            for word in line:
                if word["text"] == "SOLES":
                    word["text"] = "DÓLARES"

    (statement,) = _parse_pages(pages)

    assert statement.currency == "USD"


def test_a_statement_without_a_period_line_is_rejected() -> None:
    with pytest.raises(ValueError, match="could not find the account number"):
        _parse_pages(_without(_pages(), "Al"))
