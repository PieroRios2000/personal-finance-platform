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
from pathlib import Path

import pikepdf
import pytest
import requests

from ingestion import organizer
from tests.fixtures.synthetic_pdfs import bcp_statement_pdf

pytestmark = pytest.mark.portal

_DEX = os.environ.get("PFP_E2E_DEX_URL", "http://localhost:5556")
_REGISTER = os.environ.get("PFP_E2E_REGISTER_URL", "http://localhost:5559")
_UPLOAD = os.environ.get("PFP_E2E_UPLOAD_URL", "http://localhost:5560")
_EMAIL = "ana.perez@example.com"
_PASSWORD = "an-account-password-1"
_PDF_PASSWORD = "the-statement-password"


def _encrypted_bcp() -> bytes:
    buffer = io.BytesIO()
    with pikepdf.open(io.BytesIO(b"$BOP$" + bcp_statement_pdf())) as plain:
        plain.save(buffer, encryption=pikepdf.Encryption(owner="o", user=_PDF_PASSWORD))
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
    session: requests.Session, csrf: str, content: bytes, *, password: str, bank: str
) -> str:
    response = session.post(
        f"{_UPLOAD}/upload",
        data={"csrf": csrf, "bank": bank, "password": password},
        files={"files": ("statement.pdf", content, "application/pdf")},
        timeout=60,
    )
    return response.text


def test_the_login_form_offers_the_links_to_sign_up_and_reset() -> None:
    login = requests.get(f"{_UPLOAD}/", timeout=30)

    assert "Forgot your password?" in login.text
    assert "Create an account" in login.text


def test_someone_can_sign_up_sign_in_upload_and_the_pipeline_reads_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session, csrf = _signed_in_session()
    inbox = Path(os.environ["PFP_INBOX_DIR"])

    assert "wrong password" in _upload(
        session, csrf, _encrypted_bcp(), password="guess", bank="BCP"
    )
    assert "not a readable PDF" in _upload(
        session, csrf, b"not a pdf", password="", bank="BCP"
    )
    assert not list(inbox.glob("*/*.pdf"))  # neither was stored

    assert "statement.pdf: saved." in _upload(
        session, csrf, _encrypted_bcp(), password=_PDF_PASSWORD, bank="BCP"
    )

    (folder,) = [d for d in inbox.iterdir() if d.is_dir()]
    assert "@" not in folder.name and re.fullmatch(r"anaperez-[0-9a-f]{4}", folder.name)
    (stored,) = folder.glob("*.pdf")
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    with pikepdf.open(stored) as pdf:  # unlocked: opens with no password
        assert not pdf.is_encrypted

    # The owner's side: none of the owner's bank passwords exist here.
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "0" * 64)
    for name in ("BCP_PDF_PASSWORD", "SCOTIABANK_PDF_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    report = organizer.organize(
        folder.name, inbox_root=inbox, archive_root=tmp_path / "archive"
    )
    assert len(report.archived) == 1 and not report.needs_review


def test_a_form_without_the_pages_own_token_is_refused() -> None:
    session, _ = _signed_in_session()

    assert "The form expired" in _upload(
        session, "not-the-token", b"x", password="", bank="BCP"
    )


def test_an_upload_without_signing_in_goes_to_the_login() -> None:
    response = requests.post(f"{_UPLOAD}/upload", data={"bank": "BCP"}, timeout=30)

    assert response.url.startswith(_DEX)
