"""Tests for ingestion.submissions: one upload request, kept or refused whole (T48)."""

import stat
from pathlib import Path

from ingestion import submissions


def _create(
    root: Path, *, review: bool = False, files: int = 2
) -> submissions.Manifest:
    return submissions.create(
        root / "ana-1111",
        email="ana@example.com",
        kind="account",
        bank="BCP",
        currency="PEN",
        contents=[b"%PDF-one", b"%PDF-two"][:files],
        review=review,
    )


def test_a_submission_is_a_private_folder_of_its_files_and_a_manifest(
    tmp_path: Path,
) -> None:
    manifest = _create(tmp_path)
    folder = tmp_path / "ana-1111" / submissions.FOLDER / manifest.id

    assert sorted(p.name for p in folder.iterdir()) == [
        "01.pdf",
        "02.pdf",
        submissions.MANIFEST,
    ]
    assert stat.S_IMODE((folder / "01.pdf").stat().st_mode) == 0o600
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert submissions.read(folder) == manifest
    assert manifest.status == submissions.RECEIVED and manifest.files == 2


def test_a_kind_no_parser_reads_starts_in_review(tmp_path: Path) -> None:
    assert _create(tmp_path, review=True).status == submissions.REVIEW


def test_find_returns_only_the_statuses_asked_for_with_their_user(
    tmp_path: Path,
) -> None:
    waiting = _create(tmp_path)
    _create(tmp_path, review=True)

    found = submissions.find(tmp_path, submissions.RECEIVED)

    assert [(user, m.id) for user, _folder, m in found] == [("ana-1111", waiting.id)]


def test_the_pipeline_never_looks_in_the_submissions_folder(tmp_path: Path) -> None:
    _create(tmp_path)
    organizer = Path(__file__).resolve().parent.parent / "ingestion" / "organizer.py"

    assert not list((tmp_path / "ana-1111").glob("*.pdf"))
    assert 'inbox.glob("*.pdf")' in organizer.read_text()


def test_the_emails_say_counts_and_file_numbers_never_names() -> None:
    manifest = submissions.Manifest(
        id="ab12cd34",
        email="ana@example.com",
        kind="account",
        bank="BCP",
        currency="PEN",
        files=3,
        status=submissions.RECEIVED,
        created="2026-09-27T00:00:00+00:00",
        reason="file 2: its balances do not add up",
        loaded=5,
        duplicates=1,
    )

    received = "\n".join(submissions.received_mail(manifest))
    accepted = "\n".join(submissions.accepted_mail(manifest))
    rejected = "\n".join(submissions.rejected_mail(manifest))

    assert "3 file(s): BCP, account, PEN" in received and "under review" in received
    assert "5 statement(s)" in accepted and "1 file(s) were already loaded" in accepted
    assert "rejected as a whole" in rejected and "file 2: its balances" in rejected
    assert ".pdf" not in received + accepted + rejected


def test_a_request_in_review_tells_the_person_it_is_not_read_yet(
    tmp_path: Path,
) -> None:
    subject, body = submissions.received_mail(_create(tmp_path, review=True))

    assert "not read automatically yet" in body and "decision" in body
