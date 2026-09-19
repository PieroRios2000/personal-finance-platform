"""Tests for `ingestion.organizer`: files inbox PDFs into the standard archive (T12b).

Duplicate detection here is scoped to *within one `organize()` run*: two files in the
inbox with identical bytes. There is no persistent "already ingested" registry yet
(that's T14's bronze writer) — see the module docstring in `ingestion/organizer.py`.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion import organizer
from tests.fixtures.synthetic_pdfs import DEFAULT_MOVEMENTS, Movement, bcp_statement_pdf

# Last 4 digits are distinct and easy to recognize in assertions (0001/0002/0003).
_ACCOUNT_A = "191-00000000-0-0001"
_ACCOUNT_B = "191-00000000-0-0002"
_ACCOUNT_C = "191-00000000-0-0003"

_JAN_MOVEMENTS = (Movement(date(2026, 1, 5), "COMPRA FICTICIA", Decimal("-50.00")),)


@pytest.fixture(autouse=True)
def account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")


def _bcp_pdf(
    *,
    account_number: str = _ACCOUNT_A,
    movements: Sequence[Movement] = DEFAULT_MOVEMENTS,
    opening_balance: Decimal = Decimal("1000.00"),
    reconciles: bool = True,
) -> bytes:
    """A synthetic statement with BCP's real `$BOP$` byte prefix (T9), so
    `dispatcher.detect()` recognizes it the way it would a real BCP file."""
    return b"$BOP$" + bcp_statement_pdf(
        account_number=account_number,
        movements=movements,
        opening_balance=opening_balance,
        reconciles=reconciles,
    )


def _blank_pdf() -> bytes:
    """A valid, unencrypted, one-page PDF with no BCP content at all: real bytes
    pikepdf/pdfplumber can open, but none of bcp.parse()'s regexes match, so it
    exercises the "malformed statement" (ValueError) path rather than "wrong
    password" or "unrecognized bank"."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(10, 10, "NOT A BANK STATEMENT")
    return bytes(pdf.output())


def _drop(inbox: Path, name: str, content: bytes) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_bytes(content)
    return path


def test_pdfs_sharing_a_display_name_from_different_accounts_land_apart(
    tmp_path: Path,
) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    _drop(inbox, "EECC.pdf", _bcp_pdf(account_number=_ACCOUNT_A))
    _drop(inbox, "EECC (1).pdf", _bcp_pdf(account_number=_ACCOUNT_B))
    _drop(inbox, "EECC (2).pdf", _bcp_pdf(account_number=_ACCOUNT_C))

    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert len(report.archived) == 3
    dest_dirs = {item.dest.parent for item in report.archived}
    assert len(dest_dirs) == 3  # three different account folders
    for item in report.archived:
        assert item.dest.exists()
        assert item.bank == "BCP"
        # One archived file carries every Statement its parse produced (T18);
        # a BCP statement always produces exactly one.
        assert len(item.statements) == 1
    assert not report.duplicates
    assert not report.needs_review


def test_a_genuine_repeat_lands_in_duplicates(tmp_path: Path) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    content = _bcp_pdf()
    _drop(inbox, "EECC.pdf", content)
    _drop(inbox, "EECC (1).pdf", content)  # identical bytes, different name

    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert len(report.archived) == 1
    assert len(report.duplicates) == 1
    duplicates_dir = archive_root / "piero" / "_duplicates"
    assert list(duplicates_dir.glob("*.pdf"))

    text = report.render()
    assert "Duplicates" in text
    assert "EECC" not in text  # the raw inbox filename never reaches the report


def test_an_unreadable_pdf_lands_in_needs_review(tmp_path: Path) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    _drop(inbox, "mystery.pdf", b"not a recognizable statement at all")

    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert not report.archived
    assert len(report.needs_review) == 1
    assert "no bank recognized" in report.needs_review[0].reason
    needs_review_dir = archive_root / "piero" / "_needs_review"
    assert list(needs_review_dir.glob("*.pdf"))

    text = report.render()
    assert "Needs review" in text
    assert "mystery.pdf" not in text  # the raw inbox filename never reaches the report


def test_a_wrong_password_lands_in_needs_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BCP_PDF_PASSWORD", "wrong-password")
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    with_password = b"$BOP$" + _encrypted_bcp_pdf()
    _drop(inbox, "locked.pdf", with_password)

    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert not report.archived
    assert len(report.needs_review) == 1
    assert "password" in report.needs_review[0].reason


def test_a_statement_that_does_not_reconcile_lands_in_needs_review(
    tmp_path: Path,
) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    _drop(inbox, "broken.pdf", _bcp_pdf(reconciles=False))

    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert not report.archived
    assert len(report.needs_review) == 1
    assert "did not reconcile" in report.needs_review[0].reason


def test_a_malformed_statement_lands_in_needs_review(tmp_path: Path) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    _drop(inbox, "blank.pdf", b"$BOP$" + _blank_pdf())

    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert not report.archived
    assert len(report.needs_review) == 1
    assert "could not parse" in report.needs_review[0].reason


def _encrypted_bcp_pdf() -> bytes:
    import io

    import pikepdf

    plain = bcp_statement_pdf()
    with pikepdf.open(io.BytesIO(plain)) as pdf:
        buffer = io.BytesIO()
        pdf.save(buffer, encryption=pikepdf.Encryption(owner="secret", user="secret"))
        return buffer.getvalue()


def test_never_deletes_the_original_file(tmp_path: Path) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    _drop(inbox, "statement.pdf", _bcp_pdf())
    _drop(inbox, "mystery.pdf", b"not a recognizable statement")

    organizer.organize("piero", inbox_root=inbox_root, archive_root=archive_root)

    # The inbox itself is emptied (files moved out), but nothing vanished: every
    # file that left the inbox is findable somewhere under the archive root.
    assert not list(inbox.glob("*.pdf"))
    archived_names = {p.name for p in archive_root.rglob("*.pdf")}
    assert "statement.pdf" not in archived_names  # renamed to its period on success
    assert "mystery.pdf" in archived_names  # kept as-is under _needs_review/


def test_a_regenerated_statement_is_filed_as_a_new_version(tmp_path: Path) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    original = _bcp_pdf(movements=_JAN_MOVEMENTS)
    _drop(inbox, "EECC.pdf", original)
    organizer.organize("piero", inbox_root=inbox_root, archive_root=archive_root)

    # A regenerated PDF for the very same account and period, but different bytes
    # (a different opening balance changes the content without changing the period).
    regenerated = _bcp_pdf(movements=_JAN_MOVEMENTS, opening_balance=Decimal("2000.00"))
    _drop(inbox, "EECC-nuevo.pdf", regenerated)
    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert len(report.archived) == 1
    assert report.archived[0].version == 2
    assert report.archived[0].dest.name.endswith("_v2.pdf")
    # The original first version is still there, untouched.
    original_dest = report.archived[0].dest.parent / report.archived[
        0
    ].dest.name.replace("_v2", "")
    assert original_dest.exists()

    # A second regeneration keeps climbing the version number instead of
    # colliding with _v2.
    regenerated_again = _bcp_pdf(
        movements=_JAN_MOVEMENTS, opening_balance=Decimal("3000.00")
    )
    _drop(inbox, "EECC-nuevo-2.pdf", regenerated_again)
    report_v3 = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert report_v3.archived[0].version == 3
    assert report_v3.archived[0].dest.name.endswith("_v3.pdf")


def test_a_duplicate_of_an_already_archived_statement_is_caught_on_a_later_run(
    tmp_path: Path,
) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    content = _bcp_pdf(movements=_JAN_MOVEMENTS)
    _drop(inbox, "EECC.pdf", content)
    organizer.organize("piero", inbox_root=inbox_root, archive_root=archive_root)

    # The exact same bytes show up again in a later, separate inbox pass.
    _drop(inbox, "EECC-again.pdf", content)
    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert not report.archived
    assert len(report.duplicates) == 1
    assert "already archived" in report.duplicates[0].reason


def test_two_needs_review_items_sharing_a_name_do_not_collide(
    tmp_path: Path,
) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    _drop(inbox, "mystery.pdf", b"first unreadable content")
    organizer.organize("piero", inbox_root=inbox_root, archive_root=archive_root)

    # A different unreadable file, dropped under the very same original name in
    # a later pass.
    _drop(inbox, "mystery.pdf", b"second, different unreadable content")
    organizer.organize("piero", inbox_root=inbox_root, archive_root=archive_root)

    needs_review_dir = archive_root / "piero" / "_needs_review"
    names = {p.name for p in needs_review_dir.glob("*.pdf")}
    assert names == {"mystery.pdf", "mystery-2.pdf"}


def test_report_shows_archived_periods_and_a_gap_per_account(tmp_path: Path) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    _drop(inbox, "jan.pdf", _bcp_pdf(movements=_JAN_MOVEMENTS))
    # March, skipping February on purpose, to produce a gap.
    march_movements = (
        Movement(date(2026, 3, 5), "COMPRA FICTICIA", Decimal("-50.00")),
    )
    _drop(inbox, "mar.pdf", _bcp_pdf(movements=march_movements))

    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )
    text = report.render()

    assert "2026-02" in text  # the missing month is called out
    assert "BCP" in text and "0001" in text  # last 4 of _ACCOUNT_A


def test_gap_detection_wraps_across_a_year_boundary(tmp_path: Path) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    december_movements = (
        Movement(date(2025, 12, 5), "COMPRA FICTICIA", Decimal("-50.00")),
    )
    february_movements = (
        Movement(date(2026, 2, 5), "COMPRA FICTICIA", Decimal("-50.00")),
    )
    _drop(inbox, "dec.pdf", _bcp_pdf(movements=december_movements))
    _drop(inbox, "feb.pdf", _bcp_pdf(movements=february_movements))

    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )
    text = report.render()

    assert "2026-01" in text  # January, skipped, spans the year boundary


def test_inbox_root_and_archive_root_are_configurable(tmp_path: Path) -> None:
    inbox_root = tmp_path / "custom-inbox"
    archive_root = tmp_path / "custom-archive"
    _drop(inbox_root / "ana", "statement.pdf", _bcp_pdf())

    report = organizer.organize("ana", inbox_root=inbox_root, archive_root=archive_root)

    assert report.archived
    assert report.archived[0].dest.is_relative_to(archive_root / "ana")


def test_an_empty_or_missing_inbox_produces_an_empty_report(tmp_path: Path) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"

    report = organizer.organize(
        "nobody", inbox_root=inbox_root, archive_root=archive_root
    )

    assert not report.archived
    assert not report.duplicates
    assert not report.needs_review


def _same_content_other_bytes(pdf: bytes) -> bytes:
    """What a bank's re-download looks like: the identical statement, but the file
    itself differs (an embedded timestamp, a re-saved xref). A trailing comment is
    enough to change every byte-level hash while every parsed value stays the same."""
    variant = pdf + b"\n% regenerated by the bank on another day\n"
    assert variant != pdf
    return variant


def test_a_regenerated_pdf_with_identical_content_is_a_duplicate_not_a_new_version(
    tmp_path: Path,
) -> None:
    """Real case: the bank hands out a fresh PDF each download, so the same month
    arrives twice with different bytes. Filing it as `_v2` made
    `assert_statement_continuity` reject the period as a duplicate and skip the
    whole silver/gold build -- for a statement whose numbers are identical."""
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    original = _bcp_pdf(movements=_JAN_MOVEMENTS)
    _drop(inbox, "EECC.pdf", original)
    first = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )
    archived_dir = first.archived[0].dest.parent

    _drop(inbox, "EECC-redownloaded.pdf", _same_content_other_bytes(original))
    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert not report.archived
    assert len(report.duplicates) == 1
    assert "same content" in report.duplicates[0].reason
    assert not list(archived_dir.glob("*_v2.pdf"))
    assert len(list(archived_dir.glob("*.pdf"))) == 1
    assert list((archive_root / "piero" / "_duplicates").glob("*.pdf"))


def test_identical_content_is_compared_against_every_archived_version(
    tmp_path: Path,
) -> None:
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    _drop(inbox, "v1.pdf", _bcp_pdf(movements=_JAN_MOVEMENTS))
    organizer.organize("piero", inbox_root=inbox_root, archive_root=archive_root)
    # A genuine correction of the same period: different numbers, so a real _v2.
    correction = _bcp_pdf(movements=_JAN_MOVEMENTS, opening_balance=Decimal("2000.00"))
    _drop(inbox, "v2.pdf", correction)
    second = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )
    assert second.archived[0].version == 2

    # Now that correction is downloaded again: it matches _v2, not the original.
    _drop(inbox, "v2-again.pdf", _same_content_other_bytes(correction))
    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert not report.archived
    assert len(report.duplicates) == 1
    assert not list(second.archived[0].dest.parent.glob("*_v3.pdf"))


def test_a_regenerated_pdf_is_still_a_new_version_when_the_archived_copy_is_unreadable(
    tmp_path: Path,
) -> None:
    """If the archived twin can't be parsed to compare against, the safe answer is
    the old one: keep both, as a new version, and let the continuity test decide."""
    inbox_root, archive_root = tmp_path / "inbox", tmp_path / "raw"
    inbox = inbox_root / "piero"
    original = _bcp_pdf(movements=_JAN_MOVEMENTS)
    _drop(inbox, "EECC.pdf", original)
    first = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )
    first.archived[0].dest.write_bytes(b"not a pdf any more")

    _drop(inbox, "EECC-again.pdf", _same_content_other_bytes(original))
    report = organizer.organize(
        "piero", inbox_root=inbox_root, archive_root=archive_root
    )

    assert len(report.archived) == 1
    assert report.archived[0].version == 2
