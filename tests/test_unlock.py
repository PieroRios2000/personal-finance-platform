"""Tests for ingestion.unlock: what the upload portal stores (T44, ADR 0040)."""

import io
from pathlib import Path

import pikepdf
import pytest

from ingestion import unlock
from tests.fixtures.synthetic_pdfs import scotiabank_statement_pdf


def _locked(password: str) -> bytes:
    buffer = io.BytesIO()
    with pikepdf.open(io.BytesIO(scotiabank_statement_pdf())) as plain:
        plain.save(buffer, encryption=pikepdf.Encryption(owner="o", user=password))
    return buffer.getvalue()


def test_the_stored_copy_opens_with_no_password_and_carries_the_bank(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stored.pdf"
    path.write_bytes(unlock.unlock(_locked("theirs"), password="theirs", bank="BCP"))

    with pikepdf.open(path) as pdf:  # no password: it is unlocked
        assert not pdf.is_encrypted
    assert unlock.hinted_bank(path) == "BCP"


def test_a_wrong_password_is_refused_and_nothing_is_returned() -> None:
    with pytest.raises(pikepdf.PasswordError):
        unlock.unlock(_locked("theirs"), password="guess", bank="BCP")


def test_something_that_is_not_a_pdf_is_refused() -> None:
    with pytest.raises(pikepdf.PdfError):
        unlock.unlock(b"not a pdf", password="", bank="BCP")


def test_a_file_that_never_went_through_the_portal_has_no_hint(tmp_path: Path) -> None:
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(scotiabank_statement_pdf())
    locked = tmp_path / "locked.pdf"
    locked.write_bytes(_locked("theirs"))

    assert unlock.hinted_bank(plain) is None
    assert unlock.hinted_bank(locked) is None  # cannot be opened: no hint, no error
    assert unlock.hinted_bank(tmp_path / "missing.pdf") is None


def test_the_kind_is_recorded_beside_the_bank(tmp_path: Path) -> None:
    path = tmp_path / "stored.pdf"
    path.write_bytes(
        unlock.unlock(
            _locked("theirs"), password="theirs", bank="Interbank", kind="card"
        )
    )

    assert unlock.tags(path) == ("Interbank", "card")
    assert unlock.tags(tmp_path / "missing.pdf") == (None, None)
