"""Tests for scripts.review_uploads: what waits for the owner to study (T46)."""

from pathlib import Path

import pytest

from ingestion import unlock
from scripts import review_uploads
from tests.fixtures.synthetic_pdfs import scotiabank_statement_pdf


def _park(root: Path, user: str, bank: str, kind: str) -> None:
    folder = root / user / review_uploads.REVIEW_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    content = unlock.unlock(
        scotiabank_statement_pdf(), password="", bank=bank, kind=kind
    )
    (folder / f"{len(list(folder.iterdir()))}.pdf").write_bytes(content)


def test_files_waiting_are_counted_by_bank_and_kind_with_no_file_names(
    tmp_path: Path,
) -> None:
    _park(tmp_path, "ana-1111", "Interbank", "card")
    _park(tmp_path, "ana-1111", "Interbank", "card")
    _park(tmp_path, "bea-2222", "Interbank", "card")
    _park(tmp_path, "bea-2222", "BCP", "card")
    (tmp_path / "ana-1111" / "plain-inbox-file.pdf").write_bytes(b"not for review")

    text = review_uploads.render(review_uploads.pending(tmp_path))

    assert text.splitlines() == [
        "bank | kind | files | people",
        "BCP | card | 1 | 1",
        "Interbank | card | 3 | 2",
    ]
    assert ".pdf" not in text and "ana-1111" not in text


def test_nothing_waiting_says_so(tmp_path: Path) -> None:
    assert review_uploads.render(review_uploads.pending(tmp_path)) == (
        "Nothing waiting for review."
    )


def test_main_prints_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _park(tmp_path, "ana-1111", "Interbank", "account")

    assert review_uploads.main(["--inbox-root", str(tmp_path)]) == 0
    assert "Interbank | account | 1 | 1" in capsys.readouterr().out
