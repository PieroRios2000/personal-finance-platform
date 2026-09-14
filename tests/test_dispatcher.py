"""Tests for ingestion.dispatcher: pick a bank parser by content (T12, T18)."""

import io
from pathlib import Path

import pikepdf
import pytest

from ingestion import dispatcher
from tests.fixtures.synthetic_pdfs import bcp_statement_pdf, scotiabank_statement_pdf


def _encrypted(content: bytes, *, password: str) -> bytes:
    buffer = io.BytesIO()
    with pikepdf.open(io.BytesIO(content)) as plain:
        plain.save(buffer, encryption=pikepdf.Encryption(owner="owner", user=password))
    return buffer.getvalue()


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


def test_detect_finds_scotiabank_by_decrypting_with_its_own_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scotiabank has no byte-prefix signature to check the way BCP does (a
    real Scotiabank PDF's raw bytes start with a plain `%PDF-`): it's found by
    the second, password-fallback pass instead."""
    monkeypatch.setenv("SCOTIABANK_PDF_PASSWORD", "the-real-password")
    path = tmp_path / "statement.pdf"
    path.write_bytes(
        _encrypted(scotiabank_statement_pdf(), password="the-real-password")
    )

    entry = dispatcher.detect(path)

    assert entry.bank == "Scotiabank"
    assert entry.password_env == "SCOTIABANK_PDF_PASSWORD"


def test_detect_prefers_the_fast_bcp_path_and_never_needs_a_password_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BCP's byte-prefix check must stay instant and never depend on any
    environment variable — including one that happens to be wrong or unset."""
    monkeypatch.delenv("BCP_PDF_PASSWORD", raising=False)
    monkeypatch.delenv("SCOTIABANK_PDF_PASSWORD", raising=False)
    path = tmp_path / "statement.pdf"
    path.write_bytes(b"$BOP$" + bcp_statement_pdf())

    entry = dispatcher.detect(path)

    assert entry.bank == "BCP"


def test_detect_does_not_match_scotiabank_with_the_wrong_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCOTIABANK_PDF_PASSWORD", "not-the-real-password")
    path = tmp_path / "statement.pdf"
    path.write_bytes(
        _encrypted(scotiabank_statement_pdf(), password="correct-password")
    )

    with pytest.raises(dispatcher.UnrecognizedBankError):
        dispatcher.detect(path)
