"""Tests for scripts.review_uploads: what waits for the owner to study (T46, T48)."""

from pathlib import Path

import pytest

from ingestion import submissions
from scripts import review_uploads


def _submit(root: Path, user: str, bank: str, status: str, files: int = 1) -> str:
    manifest = submissions.create(
        root / user,
        email=f"{user}@example.com",
        kind="card",
        bank=bank,
        currency="PEN",
        contents=[b"%PDF-"] * files,
        review=status == submissions.REVIEW,
    )
    return manifest.id


def test_only_requests_waiting_for_review_are_listed_with_no_file_or_person(
    tmp_path: Path,
) -> None:
    waiting = _submit(tmp_path, "ana-1111", "Interbank", submissions.REVIEW, files=3)
    _submit(tmp_path, "bea-2222", "BCP", submissions.RECEIVED)  # not for review

    text = review_uploads.render(tmp_path)

    assert text.splitlines() == [
        "id | bank | kind | currency | files",
        f"{waiting} | Interbank | card | PEN | 3",
    ]
    assert ".pdf" not in text and "ana-1111" not in text and "@" not in text


def test_nothing_waiting_says_so(tmp_path: Path) -> None:
    assert review_uploads.render(tmp_path) == "Nothing waiting for review."


def test_main_prints_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waiting = _submit(tmp_path, "ana-1111", "Interbank", submissions.REVIEW)

    assert review_uploads.main(["--inbox-root", str(tmp_path)]) == 0
    assert waiting in capsys.readouterr().out
