"""Tests for scripts.process_submissions: a request is read whole, accepted or rejected
as a whole, and the person is told (T48, ADR 0041)."""

import io
import subprocess
from decimal import Decimal
from pathlib import Path

import pikepdf
import pytest

from ingestion import submissions, unlock
from scripts import process_submissions as ps
from tests.fixtures.synthetic_pdfs import (
    bcp_statement_pdf,
    scotiabank_statement_pdf,
)

USER = "ana-1111"


@pytest.fixture(autouse=True)
def _account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "0" * 64)


def _as_uploaded(content: bytes, bank: str, kind: str, currency: str) -> bytes:
    return unlock.unlock(content, password="", bank=bank, kind=kind, currency=currency)


def _bcp(opening: str = "1000.00", *, reconciles: bool = True) -> bytes:
    return b"$BOP$" + bcp_statement_pdf(
        opening_balance=Decimal(opening), reconciles=reconciles
    )


def _submit(
    root: Path,
    contents: list[bytes],
    *,
    bank: str = "BCP",
    kind: str = "account",
    currency: str = "PEN",
    review: bool = False,
) -> submissions.Manifest:
    tagged = [_as_uploaded(c, bank, kind, currency) for c in contents]
    return submissions.create(
        root / USER,
        email="ana@example.com",
        kind=kind,
        bank=bank,
        currency=currency,
        contents=tagged,
        review=review,
    )


class Outbox:
    def __init__(self, error: str | None = None) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.error = error

    def __call__(self, email: str, message: tuple[str, str]) -> str | None:
        self.sent.append((email, *message))
        return self.error


def _ingest_ok(
    user_id: str, inbox_root: Path, archive_root: Path
) -> tuple[int, int, int, int]:
    return (3, 0, 0, 3)


def _status(root: Path, manifest: submissions.Manifest) -> submissions.Manifest:
    folder = root / USER / submissions.FOLDER / manifest.id
    return submissions.read(folder)


def test_a_request_whose_files_all_read_is_accepted_and_the_person_is_told(
    tmp_path: Path,
) -> None:
    manifest = _submit(tmp_path, [_bcp("1000.00"), _bcp("2000.00"), _bcp("3000.00")])
    outbox = Outbox()

    lines = ps.run(tmp_path, ingest=_ingest_ok, notify=outbox)

    assert lines == [
        f"{manifest.id} accepted: 3 statement(s), 0 duplicate(s) (emailed)"
    ]
    assert len(list((tmp_path / USER).glob(f"{manifest.id}-*.pdf"))) == 3
    saved = _status(tmp_path, manifest)
    assert saved.status == submissions.ACCEPTED and saved.loaded == 3
    ((email, subject, body),) = outbox.sent
    assert email == "ana@example.com" and "processed" in subject
    assert "3 statement(s)" in body


def test_one_bad_file_rejects_the_whole_request_and_nothing_is_loaded(
    tmp_path: Path,
) -> None:
    manifest = _submit(
        tmp_path, [_bcp("1000.00"), _bcp("2000.00", reconciles=False), _bcp("3000.00")]
    )
    outbox = Outbox()

    lines = ps.run(tmp_path, ingest=_ingest_ok, notify=outbox)

    assert "rejected (file 2: its balances do not add up)" in lines[0]
    assert not list((tmp_path / USER).glob("*.pdf"))  # not even the good ones
    saved = _status(tmp_path, manifest)
    assert saved.status == submissions.REJECTED
    assert saved.reason == "file 2: its balances do not add up"
    assert "rejected" in outbox.sent[0][1]
    assert "file 2: its balances" in outbox.sent[0][2]


@pytest.mark.parametrize(
    ("content", "bank", "kind", "currency", "why"),
    [
        # A page with words but no statement in it.
        (b"", "BCP", "account", "PEN", "could not be read"),
        # A card statement sent as a bank account.
        (
            scotiabank_statement_pdf(),
            "Scotiabank",
            "account",
            "BOTH",
            "not a bank account statement",
        ),
        # A soles statement sent as dollars.
        (_bcp(), "BCP", "account", "USD", "its currency is not USD"),
        # A card with soles and dollars, said to be soles only.
        (scotiabank_statement_pdf(), "Scotiabank", "card", "PEN", "its currency"),
    ],
)
def test_a_file_that_is_not_what_was_said_is_rejected(
    tmp_path: Path, content: bytes, bank: str, kind: str, currency: str, why: str
) -> None:
    if not content:
        buffer = io.BytesIO()
        pdf = pikepdf.Pdf.new()
        pdf.add_blank_page()
        pdf.save(buffer)
        content = buffer.getvalue()
    manifest = _submit(tmp_path, [content], bank=bank, kind=kind, currency=currency)

    ps.run(tmp_path, ingest=_ingest_ok, notify=Outbox())

    saved = _status(tmp_path, manifest)
    assert saved.status == submissions.REJECTED and why in saved.reason


def test_a_card_with_soles_and_dollars_is_accepted_when_both_is_chosen(
    tmp_path: Path,
) -> None:
    manifest = _submit(
        tmp_path,
        [scotiabank_statement_pdf()],
        bank="Scotiabank",
        kind="card",
        currency="BOTH",
    )

    ps.run(tmp_path, ingest=_ingest_ok, notify=Outbox())

    assert _status(tmp_path, manifest).status == submissions.ACCEPTED


def test_a_fillable_form_dressed_as_a_statement_is_rejected(tmp_path: Path) -> None:
    """Values typed into form fields are not the page text the parsers read, and a
    made-up page never reconciles: it is rejected, not crashed on."""
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page()
    field = pdf.make_indirect(
        pikepdf.Dictionary(
            FT=pikepdf.Name.Tx,
            T=pikepdf.String("saldo_final"),
            V=pikepdf.String("1000.00"),
            Rect=[10, 10, 100, 30],
            Subtype=pikepdf.Name.Widget,
            Type=pikepdf.Name.Annot,
        )
    )
    page.obj.Annots = pikepdf.Array([field])
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=[field])
    buffer = io.BytesIO()
    pdf.save(buffer)
    manifest = _submit(tmp_path, [buffer.getvalue()])
    outbox = Outbox()

    ps.run(tmp_path, ingest=_ingest_ok, notify=outbox)

    assert _status(tmp_path, manifest).status == submissions.REJECTED
    assert "file 1" in outbox.sent[0][2]


def test_the_same_file_twice_is_not_a_rejection_the_pipeline_ignores_it(
    tmp_path: Path,
) -> None:
    manifest = _submit(tmp_path, [_bcp(), _bcp()])

    def ingest(
        user_id: str, inbox_root: Path, archive_root: Path
    ) -> tuple[int, int, int, int]:
        return (1, 1, 0, 1)  # one archived, one duplicate ignored

    outbox = Outbox()
    ps.run(tmp_path, ingest=ingest, notify=outbox)

    saved = _status(tmp_path, manifest)
    assert saved.status == submissions.ACCEPTED and saved.duplicates == 1
    assert "1 file(s) were already loaded" in outbox.sent[0][2]


def test_a_failed_ingest_keeps_the_request_and_does_not_email_the_person(
    tmp_path: Path,
) -> None:
    manifest = _submit(tmp_path, [_bcp()])
    outbox = Outbox()

    lines = ps.run(tmp_path, ingest=lambda user_id, inbox, archive: None, notify=outbox)

    assert "ingest FAILED" in lines[0] and not outbox.sent
    assert "run `pfp ingest`" in _status(tmp_path, manifest).reason


def test_a_missing_email_setup_is_reported_not_a_crash(tmp_path: Path) -> None:
    _submit(tmp_path, [_bcp()])

    lines = ps.run(tmp_path, ingest=_ingest_ok, notify=Outbox(error="no smtp"))

    assert lines[0].endswith("(email not sent: no smtp)")


def test_a_request_in_review_waits_until_the_owner_decides(tmp_path: Path) -> None:
    manifest = _submit(tmp_path, [_bcp()], bank="Interbank", review=True)

    assert ps.run(tmp_path, ingest=_ingest_ok, notify=Outbox()) == []

    outbox = Outbox()
    answer = ps.decide(tmp_path, manifest.id, "reject", notify=outbox)

    assert answer == f"{manifest.id} rejected (emailed)"
    assert _status(tmp_path, manifest).status == submissions.REJECTED
    assert "we cannot read this bank" in outbox.sent[0][2]


def test_releasing_a_request_puts_it_back_in_the_queue(tmp_path: Path) -> None:
    manifest = _submit(tmp_path, [_bcp()], review=True)

    ps.decide(tmp_path, manifest.id, "release", notify=Outbox())

    assert _status(tmp_path, manifest).status == submissions.RECEIVED
    assert ps.decide(tmp_path, "nope", "reject", notify=Outbox()).startswith(
        "no submission"
    )


def test_the_listing_shows_every_request_with_its_status(tmp_path: Path) -> None:
    accepted = _submit(tmp_path, [_bcp()])
    ps.run(tmp_path, ingest=_ingest_ok, notify=Outbox())

    assert f"{accepted.id} | accepted | BCP | account | PEN | 1" in ps.listing(tmp_path)
    assert ps.listing(tmp_path / "empty") == "No submissions."


def test_pfp_ingests_output_is_read_for_the_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Done:
        returncode = 0
        stdout = (
            "Inbox: x\nArchived: 2  Duplicates: 1  Needs review: 0\n\n"
            "Bronze: 2 statement(s) written, 0 already ingested\n"
        )

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())

    assert ps.ingest_with_pfp("ana-1111", Path("in"), Path("arch")) == (2, 1, 0, 2)


# ---- the Excel workbook of savings and investments (T49)
def _excel_submission(
    root: Path, content: bytes = b"PK-not-read-here"
) -> submissions.Manifest:
    return submissions.create(
        root / USER,
        email="ana@example.com",
        kind=submissions.EXCEL,
        bank="Excel",
        currency="-",
        contents=[content],
        review=False,
        suffix=".xlsx",
    )


def test_a_workbook_that_reads_is_imported_and_the_person_is_told(
    tmp_path: Path,
) -> None:
    manifest = _excel_submission(tmp_path)
    outbox = Outbox()

    lines = ps.run(
        tmp_path,
        notify=outbox,
        check_excel=lambda path, user: [],
        import_excel=lambda path, user: 7,
    )

    assert lines == [f"{manifest.id} accepted: 7 loaded (emailed)"]
    assert _status(tmp_path, manifest).loaded == 7
    assert "a workbook of savings and investments" in outbox.sent[0][2]


def test_one_problem_rejects_the_whole_workbook_with_row_numbers_only(
    tmp_path: Path,
) -> None:
    manifest = _excel_submission(tmp_path)
    outbox = Outbox()
    imported: list[str] = []

    def never(path: Path, user: str) -> int:
        imported.append(user)
        return 1

    ps.run(
        tmp_path,
        notify=outbox,
        check_excel=lambda path, user: [
            "Ahorros row 4: saldo_final does not follow from the previous row",
            "Inversiones row 2: tipo is not aporte, retiro or valorizacion",
        ],
        import_excel=never,
    )

    assert imported == []  # nothing loaded
    saved = _status(tmp_path, manifest)
    assert saved.status == submissions.REJECTED
    assert (
        "Ahorros row 4" in outbox.sent[0][2]
        and "Inversiones row 2" in outbox.sent[0][2]
    )


def test_a_failed_import_of_a_good_workbook_is_reported_not_emailed(
    tmp_path: Path,
) -> None:
    _excel_submission(tmp_path)
    outbox = Outbox()

    lines = ps.run(
        tmp_path,
        notify=outbox,
        check_excel=lambda path, user: [],
        import_excel=lambda path, user: None,
    )

    assert "import FAILED" in lines[0] and not outbox.sent


def test_only_the_savings_sheet_being_empty_is_not_a_problem_when_funds_load() -> None:
    assert ps._NO_SAVINGS_ROWS == "Ahorros: the sheet has no rows"


def test_pfp_import_manuals_output_is_read_for_the_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Done:
        returncode = 0
        stdout = (
            "Ahorros: 2 statement(s) written (a month already loaded is replaced)\n"
            "Inversiones: 3 month(s) written\n"
        )

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())

    assert ps.import_with_pfp(Path("x.xlsx"), "ana-1111") == 5


def test_the_default_ingest_passes_this_environments_inbox_and_archive_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: `ingest_with_pfp` used to call `pfp ingest --user <id>` with no
    `--inbox-root`/`--archive-root`, so an environment whose inbox differs from the
    default (a demo, ADR 0042) silently ingested nothing -- caught live on
    `pfp-prod`."""
    captured: list[list[str]] = []

    class Done:
        returncode = 0
        stdout = (
            "Archived: 1  Duplicates: 0  Needs review: 0\n\n"
            "Bronze: 1 statement(s) written\n"
        )

    def fake_run(cmd: list[str], **kwargs: object) -> Done:
        captured.append(cmd)
        return Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    inbox, archive = tmp_path / "inbox", tmp_path / "archive"

    assert ps.ingest_with_pfp("ana-1111", inbox, archive) == (1, 0, 0, 1)
    (cmd,) = captured
    assert cmd[cmd.index("--inbox-root") + 1] == str(inbox)
    assert cmd[cmd.index("--archive-root") + 1] == str(archive)
