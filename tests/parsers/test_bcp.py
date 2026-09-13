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
from tests.fixtures.synthetic_pdfs import Movement, bcp_statement_pdf

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


def test_parse_returns_a_reconciled_statement(bcp_pdf: Path) -> None:
    statement = bcp.parse(bcp_pdf, user_id="piero", file_sha256=FILE_SHA256)

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


def test_parse_extracts_charges_and_credits_with_the_right_sign(bcp_pdf: Path) -> None:
    statement = bcp.parse(bcp_pdf, user_id="piero", file_sha256=FILE_SHA256)

    by_amount = {t.amount: t for t in statement.transactions}
    assert by_amount[Decimal("-120.50")].description == "COMPRA TIENDA FICTICIA"
    assert by_amount[Decimal("2500.00")].description == "DEPOSITO SUELDO FICTICIO"
    assert by_amount[Decimal("-85.30")].description == "PAGO SERVICIO FICTICIO"
    assert by_amount[Decimal("300.00")].description == "TRANSFERENCIA RECIBIDA FICTICIA"


def test_parse_works_on_a_pdf_with_the_real_byte_prefix(tmp_path: Path) -> None:
    path = tmp_path / "real-shaped.pdf"
    path.write_bytes(b"$BOP$" + bcp_statement_pdf())

    statement = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert len(statement.transactions) == 4


def test_parse_unlocks_an_encrypted_pdf_with_the_right_password(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    with pikepdf.open(io.BytesIO(bcp_statement_pdf())) as plain:
        plain.save(path, encryption=pikepdf.Encryption(owner="x", user="synthetic-key"))

    statement = bcp.parse(
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

    statement = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    dates = sorted(t.date for t in statement.transactions)
    assert dates == [date(2025, 12, 29), date(2026, 1, 3)]


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

    statement = bcp.parse(
        candidate, user_id="piero", file_sha256="0" * 64, password=password
    )

    assert statement.bank == "BCP"
