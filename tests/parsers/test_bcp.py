"""Tests for ingestion.parsers.bcp (T11)."""

import hashlib
import io
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pikepdf
import pytest

from ingestion.parsers import bcp
from ingestion.reconciliation import ReconciliationError
from ingestion.schema import hash_account, last4_of
from tests.fixtures.synthetic_pdfs import (
    DEFAULT_MOVEMENTS,
    Movement,
    bcp_real_layout_statement_pdf,
    bcp_statement_pdf,
)

FILE_SHA256 = hashlib.sha256(
    b"whatever bytes; only used as an opaque id here"
).hexdigest()


@pytest.fixture(autouse=True)
def account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`parse()` needs PFP_ACCOUNT_KEY to compute account_id; a fixed test value
    is fine here since no test in this file is about the key itself (T6 already
    covers that in tests/test_schema.py)."""
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")


def test_detect_recognizes_the_real_bcp_byte_prefix(tmp_path: Path) -> None:
    # The real BCP export has 5 bytes ($BOP$) before the %PDF- header (T9); the
    # synthetic fixture doesn't add them by default, so we add them here to
    # exercise the same path pikepdf already tolerates.
    path = tmp_path / "real-shaped.pdf"
    path.write_bytes(b"$BOP$" + bcp_statement_pdf())

    assert bcp.detect(path) is True


def test_detect_rejects_a_pdf_without_the_prefix(tmp_path: Path) -> None:
    path = tmp_path / "plain.pdf"
    path.write_bytes(bcp_statement_pdf())

    assert bcp.detect(path) is False


def test_detect_rejects_a_non_pdf_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("not a PDF at all")

    assert bcp.detect(path) is False


def test_parse_returns_a_list_holding_exactly_one_statement(bcp_pdf: Path) -> None:
    """`parse()` returns `list[Statement]` for every bank (T18): a BCP account
    statement covers one account in one currency, so its list always holds
    exactly one entry. Every other test in this file unpacks that list."""
    statements = bcp.parse(bcp_pdf, user_id="piero", file_sha256=FILE_SHA256)

    assert isinstance(statements, list)
    assert len(statements) == 1


def test_parse_returns_a_reconciled_statement(bcp_pdf: Path) -> None:
    [statement] = bcp.parse(bcp_pdf, user_id="piero", file_sha256=FILE_SHA256)

    assert statement.user_id == "piero"
    assert statement.bank == "BCP"
    assert statement.account_id == hash_account("BCP", "000-00000000-0-00")
    assert statement.account_last4 == last4_of("000-00000000-0-00")
    assert statement.period_start == date(2026, 1, 5)
    assert statement.period_end == date(2026, 1, 28)
    assert statement.opening_balance == Decimal("1000.00")
    assert len(statement.transactions) == 4
    for transaction in statement.transactions:
        assert transaction.source_file_sha256 == FILE_SHA256
        assert transaction.currency == "PEN"


def test_parse_marks_every_statement_as_an_asset_account(bcp_pdf: Path) -> None:
    """A BCP checking account's balance is money on hand (T18a): hardcoded
    per parser, since a bank's own product type doesn't vary per statement."""
    [statement] = bcp.parse(bcp_pdf, user_id="piero", file_sha256=FILE_SHA256)

    assert statement.account_kind == "asset"


def test_parse_extracts_charges_and_credits_with_the_right_sign(bcp_pdf: Path) -> None:
    [statement] = bcp.parse(bcp_pdf, user_id="piero", file_sha256=FILE_SHA256)

    by_amount = {t.amount: t for t in statement.transactions}
    assert by_amount[Decimal("-120.50")].description == "COMPRA TIENDA FICTICIA"
    assert by_amount[Decimal("2500.00")].description == "DEPOSITO SUELDO FICTICIO"
    assert by_amount[Decimal("-85.30")].description == "PAGO SERVICIO FICTICIO"
    assert by_amount[Decimal("300.00")].description == "TRANSFERENCIA RECIBIDA FICTICIA"


def test_parse_works_on_a_pdf_with_the_real_byte_prefix(tmp_path: Path) -> None:
    path = tmp_path / "real-shaped.pdf"
    path.write_bytes(b"$BOP$" + bcp_statement_pdf())

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert len(statement.transactions) == 4


def test_parse_unlocks_an_encrypted_pdf_with_the_right_password(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    with pikepdf.open(io.BytesIO(bcp_statement_pdf())) as plain:
        plain.save(path, encryption=pikepdf.Encryption(owner="x", user="synthetic-key"))

    [statement] = bcp.parse(
        path, user_id="piero", file_sha256=FILE_SHA256, password="synthetic-key"
    )

    assert len(statement.transactions) == 4


def test_parse_raises_reconciliation_error_when_the_statement_does_not_add_up(
    tmp_path: Path,
) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(bcp_statement_pdf(reconciles=False))

    with pytest.raises(ReconciliationError):
        bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)


def test_parse_infers_the_year_when_the_period_crosses_new_year(tmp_path: Path) -> None:
    movements = (
        Movement(date(2025, 12, 29), "COMPRA FIN DE ANIO FICTICIA", Decimal("-40.00")),
        Movement(date(2026, 1, 3), "COMPRA INICIO DE ANIO FICTICIA", Decimal("-10.00")),
    )
    path = tmp_path / "cross-year.pdf"
    path.write_bytes(
        bcp_statement_pdf(opening_balance=Decimal("500.00"), movements=movements)
    )

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    dates = sorted(t.date for t in statement.transactions)
    assert dates == [date(2025, 12, 29), date(2026, 1, 3)]


def test_parse_reads_the_real_layout_without_nro_or_periodo_labels(
    tmp_path: Path,
) -> None:
    """The real BCP statement (T9's masked dump, 2026-09) has neither "CUENTA
    NRO." nor "PERIODO" anywhere; account number and period must be found
    without those labels."""
    path = tmp_path / "real-layout.pdf"
    path.write_bytes(bcp_real_layout_statement_pdf(account_number="123-45678901-2-34"))

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert statement.account_id == hash_account("BCP", "123-45678901-2-34")
    assert statement.account_last4 == last4_of("123-45678901-2-34")


def test_parse_reads_a_two_digit_year_period(tmp_path: Path) -> None:
    path = tmp_path / "real-layout.pdf"
    path.write_bytes(bcp_real_layout_statement_pdf())

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert statement.period_start == date(2026, 1, 5)
    assert statement.period_end == date(2026, 1, 28)


def test_parse_reads_ddmmm_transaction_dates_using_the_value_date_column(
    tmp_path: Path,
) -> None:
    """The real header row has FECHA twice (processing date, then value
    date); the fixture gives them different values, so this proves the
    parser reads the *second* FECHA column, not the first."""
    path = tmp_path / "real-layout.pdf"
    path.write_bytes(bcp_real_layout_statement_pdf())

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    dates = sorted(t.date for t in statement.transactions)
    assert dates == [
        date(2026, 1, 5),
        date(2026, 1, 12),
        date(2026, 1, 20),
        date(2026, 1, 28),
    ]


def test_parse_reads_a_description_that_starts_left_of_its_own_header(
    tmp_path: Path,
) -> None:
    """A real transaction row's description *data* started well to the left
    of the "DESCRIPCION" *header* word (58pt left, in the masked dump of a
    second real statement) — closer to the FECHA (value date) header than
    its own. Naive "nearest column header to the left" assignment then
    swallows the first description word(s) into the FECHA cell, wrecking
    both the date and the description for every row: on the real statement
    this made every one of that row's date fail `_is_row_date()`, silently
    dropping the transaction and breaking reconciliation (Piero hit this on
    3 of his 4 real statements)."""
    path = tmp_path / "misaligned-description.pdf"
    path.write_bytes(bcp_real_layout_statement_pdf(row_description_x=180))

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert len(statement.transactions) == len(DEFAULT_MOVEMENTS)
    by_amount = {t.amount: t for t in statement.transactions}
    assert by_amount[Decimal("-120.50")].description == "COMPRA TIENDA FICTICIA"
    dates = sorted(t.date for t in statement.transactions)
    assert dates == [
        date(2026, 1, 5),
        date(2026, 1, 12),
        date(2026, 1, 20),
        date(2026, 1, 28),
    ]


def test_parse_ignores_a_literal_zero_printed_alongside_a_real_amount(
    tmp_path: Path,
) -> None:
    """A third real statement had a row printing "0.00" under CARGO right
    alongside a real amount under ABONO — previously raised "row ... has
    both a charge and a credit" (a genuine ValueError, since both cells
    were non-empty), even though only one of them is a real movement. A
    literal "0.00" has no monetary effect, same as an empty cell."""
    path = tmp_path / "zero-and-real.pdf"
    path.write_bytes(bcp_real_layout_statement_pdf(zero_and_real_row=Decimal("75.00")))

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert len(statement.transactions) == len(DEFAULT_MOVEMENTS) + 1
    extra = next(t for t in statement.transactions if t.amount == Decimal("75.00"))
    assert extra.description == "AJUSTE A CERO FICTICIO"


def test_parse_reports_a_clear_error_instead_of_crashing_on_garbled_charge_text(
    tmp_path: Path,
) -> None:
    """A fourth real statement crashed the whole `pfp ingest` run with a raw,
    unhandled `decimal.InvalidOperation` traceback instead of a clean error:
    some other column's boundary mismatch had leaked non-numeric text into
    the CARGO cell. `_money()` must never be called on unvalidated cell
    text; a row whose CARGO/ABONO isn't amount-shaped now raises a normal
    ValueError (caught by ingestion.organizer the same as any other
    malformed row) instead of crashing the process."""
    path = tmp_path / "garbled-charge.pdf"
    path.write_bytes(bcp_real_layout_statement_pdf(garble_first_row_charge=True))

    with pytest.raises(ValueError, match="unrecognized charge amount"):
        bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)


def test_parse_extracts_charges_and_credits_on_the_real_layout(
    tmp_path: Path,
) -> None:
    path = tmp_path / "real-layout.pdf"
    path.write_bytes(bcp_real_layout_statement_pdf())

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    by_amount = {t.amount: t for t in statement.transactions}
    assert by_amount[Decimal("-120.50")].description == "COMPRA TIENDA FICTICIA"
    assert by_amount[Decimal("2500.00")].description == "DEPOSITO SUELDO FICTICIO"


def test_parse_finds_a_closing_balance_under_a_bare_saldo_label(
    tmp_path: Path,
) -> None:
    """The real closing balance has no "ACTUAL"/"FINAL" qualifier, and its
    amount sits one line above the bare "SALDO" label rather than beside it
    (8pt apart in the real dump, past _group_lines' 3pt same-line
    tolerance). A statement that reconciles proves both the opening and
    closing balances were found correctly."""
    path = tmp_path / "real-layout.pdf"
    path.write_bytes(bcp_real_layout_statement_pdf())

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    expected_closing = Decimal("1000.00") + sum(
        (movement.amount for movement in DEFAULT_MOVEMENTS), Decimal("0.00")
    )
    assert statement.opening_balance == Decimal("1000.00")
    assert statement.closing_balance == expected_closing


def test_parse_raises_reconciliation_error_on_a_broken_real_layout_statement(
    tmp_path: Path,
) -> None:
    path = tmp_path / "real-layout-broken.pdf"
    path.write_bytes(bcp_real_layout_statement_pdf(reconciles=False))

    with pytest.raises(ReconciliationError):
        bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)


def test_parse_keeps_rows_from_different_pages_separate(tmp_path: Path) -> None:
    """A fifth real statement (4 pages) had a row corrupted with digits
    bled in from an unrelated page: `parse()` used to flatten every page's
    words into one list *before* grouping them into lines by y-position
    (`top`) alone. Two rows on different pages that happen to land at the
    same y then merge into one garbled "line" — every real BCP page
    repeats the same header row and account/period boilerplate at the same
    y positions, so this isn't a rare coincidence, it's the normal case for
    a multi-page statement. Builds a minimal 2-page statement with a
    transaction row at the *same* y on each page, with different dates,
    descriptions and amounts, and checks both come out intact and distinct."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt")
    for page_number in (1, 2):
        pdf.add_page()
        pdf.set_font("Helvetica", size=9)
        pdf.text(40, 65, "TIPO DE CUENTA MONEDA")
        pdf.text(40, 80, "123-45678901-2-34 SOLES")
        pdf.text(40, 95, "DEL 05/01/26 AL 12/01/26")
        pdf.text(40, 110, "SALDO ANTERIOR 1,000.00")
        pdf.text(40, 130, "FECHA")
        pdf.text(90, 130, "PROC.")
        pdf.text(140, 130, "FECHA")
        pdf.text(190, 130, "VALOR")
        pdf.text(240, 130, "DESCRIPCION")
        pdf.text(400, 130, "CARGOS")
        pdf.text(460, 130, "ABONOS")
        # Same y (145) on both pages: the exact collision that used to
        # merge these two, unrelated, same-position rows into one line.
        if page_number == 1:
            pdf.text(40, 145, "04ENE")
            pdf.text(140, 145, "05ENE")
            pdf.text(240, 145, "PAGE ONE FICTICIA")
            pdf.text(400, 145, "50.00")
        else:
            pdf.text(40, 145, "11ENE")
            pdf.text(140, 145, "12ENE")
            pdf.text(240, 145, "PAGE TWO FICTICIA")
            pdf.text(460, 145, "80.00")
    pdf.text(400, 175, "1,030.00")
    pdf.text(40, 185, "SALDO")
    path = tmp_path / "multi-page.pdf"
    path.write_bytes(bytes(pdf.output()))

    [statement] = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert len(statement.transactions) == 2
    by_amount = {t.amount: t for t in statement.transactions}
    assert by_amount[Decimal("-50.00")].description == "PAGE ONE FICTICIA"
    assert by_amount[Decimal("-50.00")].date == date(2026, 1, 5)
    assert by_amount[Decimal("80.00")].description == "PAGE TWO FICTICIA"
    assert by_amount[Decimal("80.00")].date == date(2026, 1, 12)


def test_parse_reports_a_bcp_looking_pdf_missing_account_period_or_balances(
    tmp_path: Path,
) -> None:
    """The FECHA/DESCRIPCION/CARGO/ABONO header row is there (so a real BCP
    statement with a still-unrecognized account/period layout gets this
    specific message, not the generic "header row not found" one)."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(40, 40, "FECHA")
    pdf.text(180, 40, "DESCRIPCION")
    pdf.text(340, 40, "CARGOS")
    pdf.text(400, 40, "ABONOS")
    path = tmp_path / "no-account-or-period.pdf"
    path.write_bytes(bytes(pdf.output()))

    with pytest.raises(ValueError, match="account number, period or balances"):
        bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)


@pytest.mark.real_pdf
def test_parses_and_reconciles_a_real_bcp_statement() -> None:
    """Runs only on the owner's machine, against their own real PDFs.

    Never asserts or prints an extracted value (ADR 0004): a successful `parse()`
    already proves detection, decryption, extraction and reconciliation all
    worked, since `parse()` raises `ReconciliationError` on any mismatch.
    """
    search_roots = [
        Path.home() / "finance-data" / "inbox",
        Path.home() / "finance-data" / "raw",
    ]
    candidate = next(
        (
            path
            for root in search_roots
            if root.exists()
            for path in root.rglob("*.pdf")
            if bcp.detect(path)
        ),
        None,
    )
    if candidate is None:
        pytest.skip("no real BCP PDF found under ~/finance-data/{inbox,raw}")
    password = os.environ.get("BCP_PDF_PASSWORD")
    if not password:
        pytest.skip("BCP_PDF_PASSWORD is not set (see .env)")

    [statement] = bcp.parse(
        candidate, user_id="piero", file_sha256="0" * 64, password=password
    )

    assert statement.bank == "BCP"
