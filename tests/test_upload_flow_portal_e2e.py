"""The upload portal end to end (T44, ADR 0040): what CI's `portal-e2e` job runs against
a real Dex, `dex-register` and `upload` brought up with `docker compose`.

The same path a person takes: sign up, sign in to the portal through Dex, upload a
password-protected statement, and have the owner's pipeline read it with none of the
owner's passwords. Deselected by default (`-m portal`); needs the services up and these
variables (CI sets them, a developer can too): PFP_E2E_DEX_URL, PFP_E2E_REGISTER_URL,
PFP_E2E_UPLOAD_URL, PFP_DEX_INVITE_CODE, PFP_INBOX_DIR."""

import io
import os
import re
import stat
from datetime import date
from decimal import Decimal
from pathlib import Path

import pikepdf
import pytest
import requests
from openpyxl import Workbook

from ingestion import manual_layout, organizer, submissions, unlock
from scripts import process_submissions, review_uploads
from tests.fixtures.synthetic_pdfs import bcp_statement_pdf

pytestmark = pytest.mark.portal

_DEX = os.environ.get("PFP_E2E_DEX_URL", "http://localhost:5556")
_REGISTER = os.environ.get("PFP_E2E_REGISTER_URL", "http://localhost:5559")
_UPLOAD = os.environ.get("PFP_E2E_UPLOAD_URL", "http://localhost:5560")
_EMAIL = "ana.perez@example.com"
_PASSWORD = "an-account-password-1"
_PDF_PASSWORD = "the-statement-password"


def _encrypted_bcp(opening: str = "1000.00", *, reconciles: bool = True) -> bytes:
    buffer = io.BytesIO()
    plain = b"$BOP$" + bcp_statement_pdf(
        opening_balance=Decimal(opening), reconciles=reconciles
    )
    with pikepdf.open(io.BytesIO(plain)) as pdf:
        pdf.save(buffer, encryption=pikepdf.Encryption(owner="o", user=_PDF_PASSWORD))
    return buffer.getvalue()


def _signed_in_session() -> tuple[requests.Session, str]:
    """Sign up on dex-register, then sign in to the portal through Dex's login form."""
    signup = requests.post(
        f"{_REGISTER}/",
        data={
            "email": _EMAIL,
            "password": _PASSWORD,
            "confirm": _PASSWORD,
            "invite_code": os.environ["PFP_DEX_INVITE_CODE"],
        },
        timeout=30,
    )
    assert "Account created" in signup.text or "already signed up" in signup.text

    session = requests.Session()
    form = session.get(f"{_UPLOAD}/", timeout=30)  # redirected to Dex's login form
    assert form.url.startswith(_DEX)
    action = re.search(r'action="([^"]+)"', form.text)
    assert action is not None
    page = session.post(
        _DEX + action.group(1).replace("&amp;", "&"),
        data={"login": _EMAIL, "password": _PASSWORD},
        timeout=30,
    )
    assert "Upload statements" in page.text  # back on the portal, signed in
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert csrf is not None
    return session, csrf.group(1)


def _upload(
    session: requests.Session,
    csrf: str,
    contents: list[bytes],
    *,
    password: str = _PDF_PASSWORD,
    bank: str = "BCP",
    kind: str = "account",
    other_bank: str = "",
    currency: str = "PEN",
    other_currency: str = "",
) -> str:
    response = session.post(
        f"{_UPLOAD}/upload",
        data={
            "csrf": csrf,
            "bank": bank,
            "kind": kind,
            "other_bank": other_bank,
            "currency": currency,
            "other_currency": other_currency,
            "password": password,
        },
        files=[
            ("files", (f"statement-{n}.pdf", content, "application/pdf"))
            for n, content in enumerate(contents, start=1)
        ],
        timeout=90,
    )
    return response.text


def _inbox() -> Path:
    return Path(os.environ["PFP_INBOX_DIR"])


def _folders() -> set[Path]:
    return set(_inbox().glob(f"*/{submissions.FOLDER}/*"))


def _request_id(answer: str) -> str:
    found = re.search(r"Request ([0-9a-f]{8}) received", answer)
    assert found is not None, answer
    return found.group(1)


def _submission(request_id: str) -> tuple[str, Path, submissions.Manifest]:
    (found,) = [
        f
        for f in submissions.find(_inbox(), *submissions.STATUSES)
        if f[2].id == request_id
    ]
    return found


class _Outbox:
    def __init__(self) -> None:
        self.sent: list[tuple[str, tuple[str, str]]] = []

    def __call__(self, email: str, message: tuple[str, str]) -> None:
        self.sent.append((email, message))


def _ingest(
    user_id: str, inbox_root: Path, archive_root: Path
) -> tuple[int, int, int, int]:
    return (2, 0, 0, 2)


def test_the_login_form_offers_the_links_to_sign_up_and_reset() -> None:
    login = requests.get(f"{_UPLOAD}/", timeout=30)

    assert "Forgot your password?" in login.text
    assert "Create an account" in login.text


def test_the_form_asks_kind_bank_and_currency() -> None:
    session, _ = _signed_in_session()

    page = session.get(f"{_UPLOAD}/", timeout=30).text

    assert "Credit card statement" in page and "Bank account statement" in page
    assert "Other bank" in page and 'name="other_bank"' in page
    assert "Soles (PEN)" in page and "Dollars (USD)" in page
    assert 'name="other_currency"' in page


def test_one_bad_file_among_several_sinks_the_whole_request() -> None:
    session, csrf = _signed_in_session()
    before = _folders()

    answer = _upload(
        session,
        csrf,
        [_encrypted_bcp("1000.00"), b"not a pdf", _encrypted_bcp("2000.00")],
    )

    assert "File 2 (statement-2.pdf): not a readable PDF" in answer
    assert "Nothing was saved" in answer
    assert _folders() == before  # not even the good ones


def test_a_wrong_password_sinks_the_whole_request() -> None:
    session, csrf = _signed_in_session()
    before = _folders()

    answer = _upload(session, csrf, [_encrypted_bcp()], password="guess")

    assert "wrong password" in answer and "Nothing was saved" in answer
    assert _folders() == before


def test_at_most_ten_files_go_in_one_request() -> None:
    session, csrf = _signed_in_session()
    before = _folders()

    answer = _upload(
        session, csrf, [_encrypted_bcp(f"{n}000.00") for n in range(1, 12)]
    )

    assert "At most 10 files in one request" in answer
    assert _folders() == before


def test_several_months_go_in_one_request_and_are_processed_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session, csrf = _signed_in_session()

    answer = _upload(
        session, csrf, [_encrypted_bcp("1000.00"), _encrypted_bcp("2000.00")]
    )

    user_id, folder, manifest = _submission(_request_id(answer))
    assert "@" not in user_id and re.fullmatch(r"anaperez-[0-9a-f]{4}", user_id)
    assert manifest.status == submissions.RECEIVED and manifest.files == 2
    assert manifest.email == _EMAIL
    stored = sorted(folder.glob("*.pdf"))
    assert len(stored) == 2 and stat.S_IMODE(stored[0].stat().st_mode) == 0o600
    with pikepdf.open(stored[0]) as pdf:  # unlocked: opens with no password
        assert not pdf.is_encrypted

    # The owner's side: none of the owner's bank passwords exist here.
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "0" * 64)
    for name in ("BCP_PDF_PASSWORD", "SCOTIABANK_PDF_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    outbox = _Outbox()
    process_submissions.run(_inbox(), ingest=_ingest, notify=outbox)

    assert submissions.read(folder).status == submissions.ACCEPTED
    assert outbox.sent[0][0] == _EMAIL and "processed" in outbox.sent[0][1][0]
    report = organizer.organize(
        user_id, inbox_root=_inbox(), archive_root=tmp_path / "archive"
    )
    assert len(report.archived) == 2 and not report.needs_review


def test_a_file_that_does_not_read_rejects_its_whole_request_after_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, csrf = _signed_in_session()
    answer = _upload(
        session,
        csrf,
        [_encrypted_bcp("1000.00"), _encrypted_bcp("2000.00", reconciles=False)],
    )
    user_id, folder, _ = _submission(_request_id(answer))
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "0" * 64)
    outbox = _Outbox()

    process_submissions.run(_inbox(), ingest=_ingest, notify=outbox)

    saved = submissions.read(folder)
    assert saved.status == submissions.REJECTED
    assert saved.reason == "file 2: its balances do not add up"
    assert not list((_inbox() / user_id).glob(f"{saved.id}-*.pdf"))
    assert "rejected" in outbox.sent[0][1][0]


def test_a_file_for_a_bank_no_parser_reads_waits_for_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, csrf = _signed_in_session()

    answer = _upload(
        session,
        csrf,
        [_encrypted_bcp()],
        bank="Other bank",
        kind="card",
        other_bank="Banco Nuevo",
    )

    _user, folder, manifest = _submission(_request_id(answer))
    assert "not read yet" in answer and manifest.status == submissions.REVIEW
    assert manifest.bank == "Banco Nuevo"
    assert unlock.tags(next(folder.glob("*.pdf"))) == ("Banco Nuevo", "card", "PEN")
    assert manifest.id in review_uploads.render(_inbox())
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "0" * 64)
    process_submissions.run(_inbox(), ingest=_ingest, notify=_Outbox())
    assert submissions.read(folder).status == submissions.REVIEW  # untouched


def test_a_supported_bank_in_another_currency_waits_too() -> None:
    session, csrf = _signed_in_session()

    answer = _upload(
        session, csrf, [_encrypted_bcp()], currency="OTHER", other_currency="euros"
    )

    _user, folder, manifest = _submission(_request_id(answer))
    assert manifest.status == submissions.REVIEW and manifest.currency == "EUROS"


def test_a_form_without_the_pages_own_token_is_refused() -> None:
    session, _ = _signed_in_session()
    before = _folders()

    assert "The form expired" in _upload(session, "not-the-token", [b"x"])
    assert _folders() == before


def test_an_upload_without_signing_in_goes_to_the_login() -> None:
    response = requests.post(f"{_UPLOAD}/upload", data={"bank": "BCP"}, timeout=30)

    assert response.url.startswith(_DEX)


def _workbook(
    savings: list[tuple[object, ...]] | None = None,
    funds: list[tuple[object, ...]] | None = None,
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = manual_layout.SHEET
    sheet.append(list(manual_layout.SAVINGS_COLUMNS))
    for row in savings or []:
        sheet.append(list(row))
    second = workbook.create_sheet(manual_layout.INVESTMENT_SHEET)
    second.append(list(manual_layout.INVESTMENT_COLUMNS))
    for row in funds or []:
        second.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


_FUNDS: list[tuple[object, ...]] = [
    ("Fondo A", date(2026, 7, 5), "aporte", 100, "PEN", 100, None),
    ("Fondo A", date(2026, 7, 31), "valorizacion", 0, "PEN", 102, None),
    ("Fondo A", date(2026, 8, 10), "retiro", 50, "PEN", 53, None),
    ("Fondo A", date(2026, 8, 31), "valorizacion", 0, "PEN", 54, None),
]


def _send_workbook(session: requests.Session, csrf: str, content: bytes) -> str:
    return session.post(
        f"{_UPLOAD}/upload-excel",
        data={"csrf": csrf},
        files={"workbook": ("finanzas.xlsx", content, "application/octet-stream")},
        timeout=60,
    ).text


def test_the_template_can_be_downloaded_and_the_page_offers_it() -> None:
    session, _ = _signed_in_session()

    page = session.get(f"{_UPLOAD}/", timeout=30).text
    downloaded = session.get(f"{_UPLOAD}/template.xlsx", timeout=30)

    assert "Savings and investments (Excel)" in page and "template.xlsx" in page
    assert downloaded.status_code == 200
    assert (
        downloaded.content == manual_layout.generic_template()
        or downloaded.content[:2] == b"PK"
    )


def test_the_untouched_template_is_refused_and_nothing_is_kept() -> None:
    session, csrf = _signed_in_session()
    before = _folders()

    answer = _send_workbook(session, csrf, manual_layout.generic_template())

    assert "example row(s) are still in the sheet" in answer
    assert "Nothing was saved" in answer and _folders() == before


def test_a_workbook_that_is_not_one_is_refused() -> None:
    session, csrf = _signed_in_session()
    before = _folders()

    answer = _send_workbook(session, csrf, b"not a workbook")

    assert "not a readable .xlsx workbook" in answer and _folders() == before


def test_a_filled_workbook_is_kept_then_read_whole_by_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, csrf = _signed_in_session()
    answer = _send_workbook(session, csrf, _workbook(funds=_FUNDS))

    user_id, folder, manifest = _submission(_request_id(answer))
    assert (
        manifest.kind == submissions.EXCEL and manifest.status == submissions.RECEIVED
    )
    assert len(list(folder.glob("*.xlsx"))) == 1 and manifest.email == _EMAIL

    monkeypatch.setenv("PFP_ACCOUNT_KEY", "0" * 64)
    outbox = _Outbox()
    process_submissions.run(_inbox(), notify=outbox, import_excel=lambda path, user: 2)

    assert submissions.read(folder).status == submissions.ACCEPTED
    assert "a workbook of savings and investments" in outbox.sent[0][1][1]


def test_a_workbook_whose_balances_do_not_follow_is_rejected_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, csrf = _signed_in_session()
    wrong_savings: list[tuple[object, ...]] = [
        ("Mi cuenta", date(2026, 7, 5), "deposito", 100, "PEN", 100),
        ("Mi cuenta", date(2026, 7, 6), "deposito", 50, "PEN", 999),
    ]
    answer = _send_workbook(
        session, csrf, _workbook(savings=wrong_savings, funds=_FUNDS)
    )
    _user, folder, _manifest = _submission(_request_id(answer))
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "0" * 64)
    outbox = _Outbox()
    imported: list[str] = []

    def never(path: Path, user: str) -> int:
        imported.append(user)
        return 1

    process_submissions.run(_inbox(), notify=outbox, import_excel=never)

    saved = submissions.read(folder)
    assert saved.status == submissions.REJECTED and "Ahorros row 3" in saved.reason
    assert imported == []  # the good investments did not load either
    assert "rejected" in outbox.sent[0][1][0]
