"""Unlocking a statement someone uploaded (T44, ADR 0040).

The upload portal asks for the PDF's password once, opens the file with it, and stores
an unlocked copy in that person's inbox: the password is never written anywhere, and the
pipeline (run later, by the owner) needs no per-person password. Unlocking loses the one
thing that told BCP's export apart from any other PDF (its `$BOP$` prefix), so the bank
the person chose is written into the file's own metadata and the dispatcher takes it as
a *hint*: the parser it names still has to parse and reconcile the statement, or the
file goes to `_needs_review` like any other (ADR 0009: the content, not what someone
typed, decides).
"""

import io
from pathlib import Path

import pikepdf

BANK_KEY = "/PFPBank"
KIND_KEY = "/PFPKind"
CURRENCY_KEY = "/PFPCurrency"
MAX_PAGES = 60  # a statement is a few pages; more is a way to make the parsers slow


class TooManyPagesError(ValueError):
    """More pages than any statement has."""


def _sanitize(pdf: pikepdf.Pdf) -> None:
    """Take out what a statement never needs and a hostile file could use: scripts,
    launch actions, embedded files and XFA forms, at the document, name-tree, page and
    annotation level. The text and the numbers the parsers read are untouched."""
    root = pdf.Root
    for key in ("/OpenAction", "/AA"):
        if key in root:
            del root[key]
    names = root.get("/Names")
    if names is not None:
        for key in ("/JavaScript", "/EmbeddedFiles"):
            if key in names:
                del names[key]
    form = root.get("/AcroForm")
    if form is not None and "/XFA" in form:
        del form["/XFA"]
    for page in pdf.pages:
        if "/AA" in page.obj:
            del page.obj["/AA"]
        for annotation in page.obj.get("/Annots", []):
            action = annotation.get("/A")
            if action is not None and str(action.get("/S")) in (
                "/JavaScript",
                "/Launch",
                "/ImportData",
                "/SubmitForm",
            ):
                del annotation["/A"]
            if "/AA" in annotation:
                del annotation["/AA"]


def unlock(
    content: bytes, *, password: str, bank: str, kind: str = "", currency: str = ""
) -> bytes:
    """The same PDF with no password, tagged with `bank`.

    Raises `pikepdf.PasswordError` for a wrong password, `pikepdf.PdfError` for
    something that is not a PDF and `TooManyPagesError` for one far too long. The caller
    tells the person which, without ever saying the password."""
    with pikepdf.open(io.BytesIO(content), password=password) as pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise TooManyPagesError
        _sanitize(pdf)
        pdf.docinfo[BANK_KEY] = bank
        if kind:
            pdf.docinfo[KIND_KEY] = kind
        if currency:
            pdf.docinfo[CURRENCY_KEY] = currency
        unlocked = io.BytesIO()
        pdf.save(unlocked)
    return unlocked.getvalue()


def tags(path: Path) -> tuple[str | None, str | None, str | None]:
    """The bank, kind and currency an upload was tagged with (any may be None)."""
    try:
        with pikepdf.open(path) as pdf:
            found = [pdf.docinfo.get(key) for key in (BANK_KEY, KIND_KEY, CURRENCY_KEY)]
    except (pikepdf.PikepdfError, OSError):
        return None, None, None
    bank, kind, currency = (None if v is None else str(v) for v in found)
    return bank, kind, currency


def hinted_bank(path: Path) -> str | None:
    """The bank an unlocked upload was tagged with, or None (an encrypted file, a file
    that never went through the portal, anything unreadable)."""
    return tags(path)[0]
