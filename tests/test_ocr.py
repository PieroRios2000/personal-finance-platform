"""Tests for ingestion.ocr (T11b): the Tesseract fallback for scanned PDF pages."""

import hashlib
import io
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

from ingestion import ocr
from ingestion.parsers import bcp
from ingestion.reconciliation import ReconciliationError
from tests.fixtures.synthetic_pdfs import bcp_scanned_statement_pdf

FILE_SHA256 = hashlib.sha256(
    b"whatever bytes; only used as an opaque id here"
).hexdigest()

# Arbitrary scale for the synthetic scanned page below; only needs to be
# self-consistent within this one source image (see the same note in
# tests/fixtures/synthetic_pdfs.py).
_PX_PER_PT = 4
_FONT_SIZE = 40
_WORD = "SALDO"
_WORD_X_PT = 100.0
_WORD_Y_PT = 200.0
# Tolerance for OCR's own text-detection jitter (font metrics, antialiasing),
# not for the dpi scaling math: a naive implementation that forgot to scale
# pixels back to points would be off by a factor of ~4x (300/72), far outside
# this tolerance.
_POSITION_TOLERANCE_PT = 8


@pytest.fixture(autouse=True)
def account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`bcp.parse()` needs PFP_ACCOUNT_KEY to compute account_id (see the same
    fixture in tests/parsers/test_bcp.py)."""
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")


def _scanned_word_pdf() -> bytes:
    """A one-page PDF with no text layer: `_WORD` is drawn with real, legible
    glyphs onto a raster image sized to exactly cover the page, at a known
    point-space position, then embedded as the page's only content.

    Same "no text layer" shape as
    tests/test_inspect_pdf_layout.py::test_reports_pages_without_text_layer,
    but with actual drawn text instead of a blank rectangle, so Tesseract has
    something to read.
    """
    pdf = FPDF(unit="pt")
    pdf.add_page()
    page_w, page_h = pdf.w, pdf.h

    image = Image.new(
        "RGB", (round(page_w * _PX_PER_PT), round(page_h * _PX_PER_PT)), "white"
    )
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=_FONT_SIZE)
    draw.text(
        (_WORD_X_PT * _PX_PER_PT, _WORD_Y_PT * _PX_PER_PT),
        _WORD,
        fill="black",
        font=font,
    )
    pdf.image(image, x=0, y=0, w=page_w)
    return bytes(pdf.output())


def test_extract_words_reads_the_text_off_a_page_with_no_text_layer() -> None:
    with pdfplumber.open(io.BytesIO(_scanned_word_pdf())) as doc:
        page = doc.pages[0]
        assert page.extract_words() == []  # confirms this really has no text layer

        words = ocr.extract_words(page)

    assert [w["text"] for w in words] == [_WORD]


def test_extract_words_positions_land_in_point_space_not_pixel_space() -> None:
    with pdfplumber.open(io.BytesIO(_scanned_word_pdf())) as doc:
        words = ocr.extract_words(doc.pages[0])

    word = words[0]
    assert word["x0"] == pytest.approx(_WORD_X_PT, abs=_POSITION_TOLERANCE_PT)
    assert word["top"] == pytest.approx(_WORD_Y_PT, abs=_POSITION_TOLERANCE_PT)
    assert word["x1"] > word["x0"]
    assert word["bottom"] > word["top"]


def test_extract_words_skips_whitespace_only_entries(tmp_path: Path) -> None:
    # A blank page: Tesseract may still emit whitespace-only "words" for
    # detected-but-empty regions; none of them should come back.
    pdf = FPDF(unit="pt")
    pdf.add_page()
    page_w, page_h = pdf.w, pdf.h
    image = Image.new("RGB", (round(page_w * 4), round(page_h * 4)), "white")
    pdf.image(image, x=0, y=0, w=page_w)

    with pdfplumber.open(io.BytesIO(bytes(pdf.output()))) as doc:
        words = ocr.extract_words(doc.pages[0])

    assert words == []


def test_bcp_parse_reconciles_a_statement_with_a_scanned_transaction_page(
    tmp_path: Path,
) -> None:
    """The transaction table lives only on a scanned (no text layer) page, so a
    successful, correctly reconciled parse proves the OCR fallback works end to
    end, through bcp.py's line-grouping and column-assignment."""
    path = tmp_path / "scanned-bcp-statement.pdf"
    path.write_bytes(bcp_scanned_statement_pdf())

    statement = bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)

    assert statement.opening_balance == Decimal("1000.00")
    assert len(statement.transactions) == 4
    by_amount = {t.amount: t for t in statement.transactions}
    assert by_amount[Decimal("-120.50")].description == "COMPRA TIENDA FICTICIA"
    assert by_amount[Decimal("2500.00")].description == "DEPOSITO SUELDO FICTICIO"


def test_bcp_parse_raises_reconciliation_error_on_a_misread_amount(
    tmp_path: Path,
) -> None:
    """A garbled digit on the scanned table -- standing in for an OCR misread --
    must fail reconciliation, not get silently accepted. This needs no extra
    code in ingestion.ocr or bcp.py: reconcile() is already OCR's safety net."""
    path = tmp_path / "scanned-bcp-statement-garbled.pdf"
    path.write_bytes(bcp_scanned_statement_pdf(garble_amount=True))

    with pytest.raises(ReconciliationError):
        bcp.parse(path, user_id="piero", file_sha256=FILE_SHA256)
