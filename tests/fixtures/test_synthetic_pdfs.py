from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber

from scripts.inspect_pdf_layout import describe
from tests.fixtures.synthetic_pdfs import DEFAULT_MOVEMENTS, Movement, bcp_statement_pdf


def raw_text(pdf_bytes: bytes, tmp_path: Path) -> str:
    """Extract unmasked text: fine here, this PDF only ever holds fictional data."""
    path = tmp_path / "raw.pdf"
    path.write_bytes(pdf_bytes)
    with pdfplumber.open(path) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


def test_reconciling_statement_prints_a_closing_balance_that_adds_up(
    tmp_path: Path,
) -> None:
    opening = Decimal("1000.00")
    movements = (
        Movement(date(2026, 1, 5), "COMPRA FICTICIA UNO", Decimal("-100.00")),
        Movement(date(2026, 1, 10), "ABONO FICTICIO DOS", Decimal("250.00")),
    )
    expected_closing = opening + sum((m.amount for m in movements), Decimal(0))

    text = raw_text(
        bcp_statement_pdf(opening_balance=opening, movements=movements), tmp_path
    )

    assert f"SALDO ACTUAL {expected_closing:,.2f}" in text


def test_reconciles_false_breaks_the_printed_closing_balance(tmp_path: Path) -> None:
    opening = Decimal("1000.00")
    movements = (Movement(date(2026, 1, 5), "COMPRA FICTICIA UNO", Decimal("-100.00")),)
    expected_closing = opening + movements[0].amount

    text = raw_text(
        bcp_statement_pdf(
            opening_balance=opening, movements=movements, reconciles=False
        ),
        tmp_path,
    )

    assert f"SALDO ACTUAL {expected_closing:,.2f}" not in text


def test_explicit_closing_balance_overrides_reconciles(tmp_path: Path) -> None:
    opening = Decimal("1000.00")
    movements = (Movement(date(2026, 1, 5), "COMPRA FICTICIA UNO", Decimal("-100.00")),)
    explicit_closing = Decimal("42.00")

    text = raw_text(
        bcp_statement_pdf(
            opening_balance=opening,
            movements=movements,
            closing_balance=explicit_closing,
            reconciles=False,
        ),
        tmp_path,
    )

    assert f"SALDO ACTUAL {explicit_closing:,.2f}" in text


def test_default_statement_is_a_well_formed_plausible_bcp_dump(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(bcp_statement_pdf())

    out = describe(path)

    assert "Encrypted: no" in out
    assert "Pages without a text layer (scanned): none" in out
    for header in ["FECHA", "DESCRIPCION", "CARGO", "ABONO", "SALDO"]:
        assert header in out
    # One line per default movement plus the header row and a few info lines.
    assert out.count("y=") >= len(DEFAULT_MOVEMENTS) + 5
    for secret in [m.description for m in DEFAULT_MOVEMENTS]:
        assert secret not in out


def test_bcp_pdf_fixture_returns_a_path_to_a_valid_unlocked_pdf(bcp_pdf: Path) -> None:
    assert bcp_pdf.exists()
    assert bcp_pdf.suffix == ".pdf"

    out = describe(bcp_pdf)

    assert "Encrypted: no" in out
    assert "SALDO" in out
