"""Tests for ingestion.dispatcher: pick a bank parser by content (T12)."""

from pathlib import Path

import pytest

from ingestion import dispatcher
from tests.fixtures.synthetic_pdfs import bcp_statement_pdf


def test_detect_finds_the_bcp_parser_for_a_bop_prefixed_pdf(tmp_path: Path) -> None:
    path = tmp_path / "statement.pdf"
    path.write_bytes(b"$BOP$" + bcp_statement_pdf())

    entry = dispatcher.detect(path)

    assert entry.bank == "BCP"
    assert entry.password_env == "BCP_PDF_PASSWORD"


def test_detect_raises_when_no_parser_recognizes_the_pdf(tmp_path: Path) -> None:
    path = tmp_path / "unknown.pdf"
    path.write_bytes(b"not a recognizable statement at all")

    with pytest.raises(dispatcher.UnrecognizedBankError):
        dispatcher.detect(path)


def test_detect_does_not_care_about_the_file_name(tmp_path: Path) -> None:
    content = b"$BOP$" + bcp_statement_pdf()
    named_normally = tmp_path / "estado-de-cuenta.pdf"
    named_oddly = tmp_path / "EECC (3).pdf"
    named_normally.write_bytes(content)
    named_oddly.write_bytes(content)

    assert dispatcher.detect(named_normally).bank == dispatcher.detect(named_oddly).bank
