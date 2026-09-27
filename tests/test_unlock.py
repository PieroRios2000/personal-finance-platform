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
            _locked("theirs"),
            password="theirs",
            bank="Interbank",
            kind="card",
            currency="EUR",
        )
    )

    assert unlock.tags(path) == ("Interbank", "card", "EUR")
    assert unlock.tags(tmp_path / "missing.pdf") == (None, None, None)


def _hostile() -> bytes:
    pdf = pikepdf.Pdf.open(io.BytesIO(scotiabank_statement_pdf()))
    script = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("x"))
    pdf.Root.OpenAction = script
    pdf.Root.AA = pikepdf.Dictionary(WC=script)
    pdf.Root.Names = pikepdf.Dictionary(
        JavaScript=pikepdf.Dictionary(Names=[]),
        EmbeddedFiles=pikepdf.Dictionary(Names=[]),
    )
    pdf.Root.AcroForm = pikepdf.Dictionary(XFA=pikepdf.Array())
    page = pdf.pages[0].obj
    page.AA = pikepdf.Dictionary(O=script)
    annotation = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Link,
            Rect=[0, 0, 10, 10],
            A=pikepdf.Dictionary(S=pikepdf.Name.Launch, F=pikepdf.String("x")),
        )
    )
    page.Annots = pikepdf.Array([annotation])
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


def test_scripts_launch_actions_and_embedded_files_are_taken_out() -> None:
    clean = unlock.unlock(_hostile(), password="", bank="BCP")

    with pikepdf.open(io.BytesIO(clean)) as pdf:
        root = pdf.Root
        assert "/OpenAction" not in root and "/AA" not in root
        assert "/JavaScript" not in root.Names and "/EmbeddedFiles" not in root.Names
        assert "/XFA" not in root.AcroForm
        assert "/AA" not in pdf.pages[0].obj
        assert "/A" not in pdf.pages[0].obj.Annots[0]


def test_a_statement_still_reads_after_it_is_cleaned() -> None:
    from ingestion import dispatcher

    clean = unlock.unlock(scotiabank_statement_pdf(), password="", bank="Scotiabank")

    assert clean and dispatcher._PARSERS  # cleaning keeps a document the parsers open


def test_a_pdf_with_far_too_many_pages_is_refused() -> None:
    pdf = pikepdf.Pdf.new()
    for _ in range(unlock.MAX_PAGES + 1):
        pdf.add_blank_page()
    buffer = io.BytesIO()
    pdf.save(buffer)

    with pytest.raises(unlock.TooManyPagesError):
        unlock.unlock(buffer.getvalue(), password="", bank="BCP")
