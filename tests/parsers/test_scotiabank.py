"""Tests for ingestion.parsers.scotiabank (T18).

No real Scotiabank PDF is used anywhere here (ADR 0004): every fixture is built
by `tests.fixtures.synthetic_pdfs.scotiabank_statement_pdf`, calibrated against a
masked layout dump the owner reviewed himself.
"""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion.parsers import scotiabank
from ingestion.schema import hash_account
from tests.fixtures.synthetic_pdfs import (
    DEFAULT_SCOTIABANK_MOVEMENTS,
    ScotiabankMovement,
    scotiabank_statement_pdf,
)

FILE_SHA256 = hashlib.sha256(
    b"whatever bytes; only used as an opaque id here"
).hexdigest()


@pytest.fixture(autouse=True)
def account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")


def test_parse_splits_soles_and_dolares_into_separate_statements(
    tmp_path: Path,
) -> None:
    """The point of T18's list[Statement] return: one card, two currencies,
    each independently reconciled, since Statement holds one opening/closing
    balance, not one per currency."""
    path = tmp_path / "statement.pdf"
    path.write_bytes(scotiabank_statement_pdf())

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    by_currency = {s.transactions[0].currency: s for s in statements}
    assert set(by_currency) == {"PEN", "USD"}
    pen, usd = by_currency["PEN"], by_currency["USD"]
    assert pen.opening_balance == Decimal("500.00")
    assert pen.closing_balance == Decimal("550.00")
    assert len(pen.transactions) == 2
    assert usd.opening_balance == Decimal("0.00")
    assert usd.closing_balance == Decimal("25.50")
    assert len(usd.transactions) == 1


def test_parse_marks_every_statement_as_a_liability_account(tmp_path: Path) -> None:
    """A credit-card balance is debt owed, not money on hand (T18a) — the
    opposite kind of thing from BCP's checking account. Every currency's
    Statement is still the same credit-card account, so all of them get
    "liability", hardcoded per parser like BCP's "asset"."""
    path = tmp_path / "statement.pdf"
    path.write_bytes(scotiabank_statement_pdf())

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert len(statements) > 1  # proves this isn't vacuously true for one
    assert all(statement.account_kind == "liability" for statement in statements)


def test_parse_sets_each_statements_own_currency(tmp_path: Path) -> None:
    """T18c: parse() builds one Statement per currency in a loop -- each one
    must carry that same loop's own currency, not a hardcoded constant (BCP's
    "PEN" wouldn't be true here, since this parser also produces "USD"
    statements)."""
    path = tmp_path / "statement.pdf"
    path.write_bytes(scotiabank_statement_pdf())

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    by_currency = {s.currency: s for s in statements}
    assert set(by_currency) == {"PEN", "USD"}
    for currency, statement in by_currency.items():
        assert all(t.currency == currency for t in statement.transactions)


def test_parse_ignores_a_stray_tag_after_a_rows_amount(tmp_path: Path) -> None:
    """Real rows sometimes end with a `(abc:12)` tag right of the amount. It
    used to be the last token of the currency cell, so the row's amount was
    never read and the statement's Total no longer matched."""
    path = tmp_path / "statement.pdf"
    path.write_bytes(scotiabank_statement_pdf(stray_tags=True))

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    by_currency = {s.currency: s for s in statements}
    assert len(by_currency["PEN"].transactions) == 2
    assert len(by_currency["USD"].transactions) == 1
    assert by_currency["PEN"].closing_balance == Decimal("550.00")


def test_parse_uses_only_the_last_total_line_as_the_closing_balance(
    tmp_path: Path,
) -> None:
    """Real multi-page statements print a "Total" at the end of every page, but
    only the last one is the closing balance (checked against real files: the
    earlier ones are not the running balance). An earlier, different Total
    must not fail a statement whose last Total is right."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt")
    for page_number in (1, 2):
        pdf.add_page()
        pdf.set_font("Helvetica", size=9)
        pdf.text(40, 20, "00000000")
        pdf.text(140, 20, "0000-0000-****-0000")
        pdf.text(40, 50, "PERIODO DE TARJETA DEL 05-01-2026 AL 12-01-2026")
        pdf.text(40, 70, "Saldo Anterior")
        pdf.text(451, 70, "500.00")
        pdf.text(40, 100, "Fecha")
        pdf.text(140, 100, "Fecha")
        pdf.text(240, 100, "Descripción")
        pdf.text(451, 110, "Soles")
        pdf.text(520, 110, "Dólares")
        pdf.text(40, 130, "04/01/26" if page_number == 1 else "11/01/26")
        pdf.text(140, 130, "05/01/26" if page_number == 1 else "12/01/26")
        pdf.text(240, 130, f"PAGE {page_number} FICTICIA")
        pdf.text(451, 130, "50.00")
        pdf.text(40, 150, "Total")
        # page 1: an intermediate figure; page 2: opening 500 + 50 + 50
        pdf.text(451, 150, "123.45" if page_number == 1 else "600.00")
    path = tmp_path / "two-totals.pdf"
    path.write_bytes(bytes(pdf.output()))

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert statements[0].closing_balance == Decimal("600.00")


def test_parse_reads_the_debt_sign_convention(tmp_path: Path) -> None:
    """A charge has no suffix and adds to debt (positive); a payment ends in
    "-" and reduces it (negative) — the opposite of BCP's convention, since
    this balance is money owed, not money on hand."""
    path = tmp_path / "statement.pdf"
    path.write_bytes(scotiabank_statement_pdf())

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    by_amount = {t.amount: t for s in statements for t in s.transactions}
    assert by_amount[Decimal("150.00")].description == "COMPRA TIENDA FICTICIA"
    assert by_amount[Decimal("-100.00")].description == "PAGO TARJETA FICTICIO"


def test_parse_uses_the_first_date_column(tmp_path: Path) -> None:
    """The credit card header has Fecha twice; the owner wants the first column
    (the fixture prints it a day before the second, so the two are told apart)."""
    path = tmp_path / "statement.pdf"
    path.write_bytes(scotiabank_statement_pdf())

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    dates = sorted(t.date for s in statements for t in s.transactions)
    assert dates == [date(2026, 1, 4), date(2026, 1, 11), date(2026, 1, 19)]


def test_parse_reads_the_account_code_and_masked_card_last4(tmp_path: Path) -> None:
    """account_id comes from the bare 8-digit code (owner-confirmed stable
    client identifier); account_last4 from the bank's own masked card number
    (9999-9999-****-9999) — the full card number is never printed at all."""
    path = tmp_path / "statement.pdf"
    path.write_bytes(scotiabank_statement_pdf(account_code="12345678"))

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    for statement in statements:
        assert statement.account_id == hash_account("Scotiabank", "12345678")
        assert statement.account_last4 == "0000"  # the fixture's masked card


def test_parse_reads_a_dashed_period(tmp_path: Path) -> None:
    path = tmp_path / "statement.pdf"
    path.write_bytes(scotiabank_statement_pdf())

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    for statement in statements:
        assert statement.period_start == date(2026, 1, 5)
        assert statement.period_end == date(2026, 1, 20)


def test_parse_rejects_a_currency_whose_total_does_not_add_up(
    tmp_path: Path,
) -> None:
    """`closing_balance` is *computed* here (opening + this parser's own
    transaction sum), so `reconcile()` itself can never disagree with it: the
    two sides of that check are built from the same formula. What actually
    catches a broken statement is the cross-check against the closing balance
    the last `Total` line declares, which fires first — a plain `ValueError`,
    not `ReconciliationError`. `test_parse_reports_a_mismatched_declared_total`
    covers the same failure built by hand; this one proves the fixture's own
    `reconciles=False` (mirroring `bcp_statement_pdf`'s contract) reaches it
    too."""
    path = tmp_path / "broken.pdf"
    path.write_bytes(scotiabank_statement_pdf(reconciles=False))

    with pytest.raises(ValueError, match="does not match opening balance plus"):
        scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)


def test_parse_reports_a_mismatched_declared_total(tmp_path: Path) -> None:
    """The last "Total" line is the statement's declared closing balance, this
    parser's one independent cross-check: a fixture whose own per-row math is
    internally consistent but whose printed Total doesn't match it must still
    fail, loudly, not silently."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(40, 20, "00000000")
    pdf.text(140, 20, "0000-0000-****-0000")
    pdf.text(40, 50, "PERIODO DE TARJETA DEL 05-01-2026 AL 05-01-2026")
    pdf.text(40, 70, "Saldo Anterior")
    pdf.text(451, 70, "500.00")
    pdf.text(520, 70, "0.00")
    pdf.text(40, 100, "Fecha")
    pdf.text(140, 100, "Fecha")
    pdf.text(240, 100, "Descripción")
    pdf.text(451, 110, "Soles")
    pdf.text(520, 110, "Dólares")
    pdf.text(40, 130, "04/01/26")
    pdf.text(140, 130, "05/01/26")
    pdf.text(240, 130, "COMPRA FICTICIA")
    pdf.text(451, 130, "150.00")
    pdf.text(40, 150, "Total")
    pdf.text(451, 150, "999.99")  # not 500.00 + 150.00, the closing balance
    path = tmp_path / "bad-total.pdf"
    path.write_bytes(bytes(pdf.output()))

    with pytest.raises(ValueError, match="does not match opening balance plus"):
        scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)


def test_parse_reports_a_missing_header_or_account_cleanly(tmp_path: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(40, 40, "nothing recognizable here")
    path = tmp_path / "empty.pdf"
    path.write_bytes(bytes(pdf.output()))

    with pytest.raises(ValueError):
        scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)


def test_parse_keeps_rows_from_different_pages_separate(tmp_path: Path) -> None:
    """Two pages, a transaction row at the identical y on each, different
    dates/descriptions/amounts on each: the exact collision that corrupted a
    real 4-page BCP statement (T18's PR) when lines were once grouped across
    the whole document instead of per page. Built the same way that bug's own
    regression test was, so this parser never repeats it."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt")
    for page_number in (1, 2):
        pdf.add_page()
        pdf.set_font("Helvetica", size=9)
        pdf.text(40, 20, "00000000")
        pdf.text(140, 20, "0000-0000-****-0000")
        pdf.text(40, 50, "PERIODO DE TARJETA DEL 05-01-2026 AL 12-01-2026")
        pdf.text(40, 70, "Saldo Anterior")
        pdf.text(451, 70, "500.00")
        pdf.text(520, 70, "0.00")
        pdf.text(40, 100, "Fecha")
        pdf.text(140, 100, "Fecha")
        pdf.text(240, 100, "Descripción")
        pdf.text(451, 110, "Soles")
        pdf.text(520, 110, "Dólares")
        # Same y (130) on both pages: the exact collision under test.
        if page_number == 1:
            pdf.text(40, 130, "04/01/26")
            pdf.text(140, 130, "05/01/26")
            pdf.text(240, 130, "PAGE ONE FICTICIA")
            pdf.text(451, 130, "50.00")
        else:
            pdf.text(40, 130, "11/01/26")
            pdf.text(140, 130, "12/01/26")
            pdf.text(240, 130, "PAGE TWO FICTICIA")
            pdf.text(451, 130, "80.00")
    path = tmp_path / "multi-page.pdf"
    path.write_bytes(bytes(pdf.output()))

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    pen = next(s for s in statements if s.transactions[0].currency == "PEN")
    assert len(pen.transactions) == 2
    by_amount = {t.amount: t for t in pen.transactions}
    assert by_amount[Decimal("50.00")].description == "PAGE ONE FICTICIA"
    assert by_amount[Decimal("50.00")].date == date(2026, 1, 4)  # the first column
    assert by_amount[Decimal("80.00")].description == "PAGE TWO FICTICIA"
    assert by_amount[Decimal("80.00")].date == date(2026, 1, 11)


def test_parse_omits_a_currency_with_no_activity(tmp_path: Path) -> None:
    """Only Soles activity in this fixture (the default USD opening balance is
    0.00 with no transactions): a currency with neither an opening balance
    entry nor any transactions shouldn't produce an empty Statement."""
    movements = (
        ScotiabankMovement(
            date(2026, 1, 5), "COMPRA UNICA FICTICIA", "PEN", Decimal("50.00")
        ),
    )
    path = tmp_path / "one-currency.pdf"
    path.write_bytes(scotiabank_statement_pdf(movements=movements, opening_usd=None))

    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert len(statements) == 1
    assert statements[0].transactions[0].currency == "PEN"


def test_parse_gives_the_same_result_under_an_arbitrary_file_name(
    tmp_path: Path,
) -> None:
    content = scotiabank_statement_pdf()
    normal = tmp_path / "statement.pdf"
    odd = tmp_path / "EECC (3).pdf"
    normal.write_bytes(content)
    odd.write_bytes(content)

    a = scotiabank.parse(normal, user_id="piero", file_sha256=FILE_SHA256)
    b = scotiabank.parse(odd, user_id="piero", file_sha256=FILE_SHA256)

    assert [s.account_id for s in a] == [s.account_id for s in b]


@pytest.mark.real_pdf
def test_parses_and_reconciles_a_real_scotiabank_statement() -> None:
    """Runs only on the owner's machine, against his own real PDF.

    Never asserts or prints an extracted value (ADR 0004): a successful
    `parse()` already proves detection, decryption, extraction and
    reconciliation all worked for every currency the statement carries, since
    `parse()` raises `ReconciliationError` on any mismatch. This parser has
    not been run against a real file yet — see brain/components/
    scotiabank-parser.md for what's confirmed vs. inferred.
    """
    import os

    from ingestion import dispatcher

    search_roots = [
        Path.home() / "finance-data" / "inbox",
        Path.home() / "finance-data" / "raw",
    ]
    password = os.environ.get("SCOTIABANK_PDF_PASSWORD")
    if not password:
        pytest.skip("SCOTIABANK_PDF_PASSWORD is not set (see .env)")

    candidate = None
    for root in search_roots:
        if not root.exists():
            continue
        for candidate_path in root.rglob("*.pdf"):
            try:
                entry = dispatcher.detect(candidate_path)
            except dispatcher.UnrecognizedBankError:
                continue
            if entry.bank == "Scotiabank":
                candidate = candidate_path
                break
        if candidate:
            break
    if candidate is None:
        pytest.skip("no real Scotiabank PDF found under ~/finance-data/{inbox,raw}")

    statements = scotiabank.parse(
        candidate, user_id="piero", file_sha256="0" * 64, password=password
    )

    assert all(s.bank == "Scotiabank" for s in statements)


def test_default_movements_cover_both_currencies() -> None:
    """A fixture-quality guard: if DEFAULT_SCOTIABANK_MOVEMENTS ever stopped
    including both currencies, several tests above would quietly start
    testing less than they claim to."""
    currencies = {m.currency for m in DEFAULT_SCOTIABANK_MOVEMENTS}
    assert currencies == {"PEN", "USD"}


def _card_pdf(*, totals: list[tuple[int, str, list[tuple[int, str]]]]) -> bytes:
    """A one-page card statement (opening 500.00 PEN and 10.00 USD, one 50.00
    PEN charge) plus extra lines: `(y, label, [(x, text), ...])`."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(40, 20, "00000000")
    pdf.text(140, 20, "0000-0000-****-0000")
    pdf.text(40, 50, "PERIODO DE TARJETA DEL 05-01-2026 AL 05-01-2026")
    pdf.text(40, 70, "Saldo Anterior")
    pdf.text(451, 70, "500.00")
    pdf.text(520, 70, "10.00")
    pdf.text(40, 100, "Fecha")
    pdf.text(140, 100, "Fecha")
    pdf.text(240, 100, "Descripción")
    pdf.text(451, 110, "Soles")
    pdf.text(520, 110, "Dólares")
    pdf.text(40, 130, "04/01/26")
    pdf.text(140, 130, "05/01/26")
    pdf.text(240, 130, "COMPRA FICTICIA")
    pdf.text(451, 130, "50.00")
    for y, label, cells in totals:
        pdf.text(40, y, label)
        for x, text in cells:
            pdf.text(x, y, text)
    return bytes(pdf.output())


def _parse_card(tmp_path: Path, data: bytes) -> dict[str, Decimal]:
    path = tmp_path / "card.pdf"
    path.write_bytes(data)
    statements = scotiabank.parse(path, user_id="piero", file_sha256=FILE_SHA256)
    return {s.currency: s.closing_balance for s in statements}


def test_parse_without_a_total_line_uses_the_computed_closing_balance(
    tmp_path: Path,
) -> None:
    assert _parse_card(tmp_path, _card_pdf(totals=[])) == {
        "PEN": Decimal("550.00"),
        "USD": Decimal("10.00"),
    }


def test_parse_ignores_a_prose_line_that_merely_contains_total(
    tmp_path: Path,
) -> None:
    """Only a line that is a label, "Total", and amounts is a Total line: a
    sentence with the word and a figure must not become the declared closing."""
    data = _card_pdf(
        totals=[
            (150, "Sub Total", [(451, "550.00"), (520, "10.00")]),
            (170, "Total de la deuda vencida", [(451, "999.99")]),
        ]
    )

    assert _parse_card(tmp_path, data)["PEN"] == Decimal("550.00")


def test_parse_takes_the_closing_from_the_last_total_line_only(
    tmp_path: Path,
) -> None:
    """A currency missing from the last Total line is not filled in from an
    earlier one (a stale, non-closing figure): it falls back to the computed
    balance instead of failing the statement."""
    data = _card_pdf(
        totals=[
            (150, "Sub Total", [(451, "123.45"), (520, "77.77")]),
            (170, "Sub Total", [(451, "550.00")]),
        ]
    )

    assert _parse_card(tmp_path, data) == {
        "PEN": Decimal("550.00"),
        "USD": Decimal("10.00"),
    }


def test_parse_skips_a_saldo_anterior_prose_line_without_amounts(
    tmp_path: Path,
) -> None:
    """A dashboard sentence printed before the real line must not shadow it."""
    data = _card_pdf(totals=[(60, "saldo del mes anterior", [])])

    assert _parse_card(tmp_path, data)["PEN"] == Decimal("550.00")
