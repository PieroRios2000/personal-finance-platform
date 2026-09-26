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


def unlock(
    content: bytes, *, password: str, bank: str, kind: str = "", currency: str = ""
) -> bytes:
    """The same PDF with no password, tagged with `bank`.

    Raises `pikepdf.PasswordError` for a wrong password and `pikepdf.PdfError` for
    something that is not a PDF (the caller tells the person, without either)."""
    with pikepdf.open(io.BytesIO(content), password=password) as pdf:
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
