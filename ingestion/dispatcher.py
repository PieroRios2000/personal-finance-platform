"""Picks the right bank parser for a PDF by its content (T12), never its file
name (ADR 0009).

Each registered parser is a plain module (`ingestion.parsers.bcp`,
`ingestion.parsers.scotiabank`) exposing `parse` and, optionally, `detect`
functions matching `ingestion.parsers.base.BankParser`. A module can't be typed
directly against that Protocol (mypy doesn't structurally match a module against
attribute Protocols), so each one is wrapped here in a small `_Parser` tuple
instead, which also carries the environment variable holding that bank's PDF
password.

Detection is two passes (T18). BCP's real export has a cheap, password-free
signature (a 5-byte prefix) to check first — `detect` is set for it. Scotiabank
has no such signature: a real Scotiabank PDF's raw bytes start with a plain
`%PDF-`, indistinguishable from any other PDF without opening it. A parser
registered with `detect=None` is tried in a second pass instead, by attempting
to decrypt the file with that bank's own password (`password_env`); the first
one that opens without raising `pikepdf.PikepdfError` (a wrong password, or a
file that isn't even a valid PDF — see `_decrypts()`) is the match. The fast
pass always runs first and never touches the environment, so BCP's detection
stays instant and never depends on any password being configured, correct or
not.
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pikepdf

from ingestion.parsers import bcp, scotiabank
from ingestion.schema import Statement


class _Parser(NamedTuple):
    bank: str
    password_env: str
    detect: Callable[[Path], bool] | None
    parse: Callable[..., list[Statement]]


_PARSERS: tuple[_Parser, ...] = (
    _Parser("BCP", "BCP_PDF_PASSWORD", bcp.detect, bcp.parse),
    _Parser("Scotiabank", "SCOTIABANK_PDF_PASSWORD", None, scotiabank.parse),
)


class UnrecognizedBankError(ValueError):
    """No registered parser recognizes this PDF."""


def _decrypts(path: Path, password: str) -> bool:
    """True if `path` opens with `password`.

    Catches `pikepdf.PikepdfError`, not just `PasswordError`: a wrong password
    against a genuinely encrypted PDF raises the latter, but a file that isn't
    a real PDF at all (or is one too damaged to open) raises a sibling
    `pikepdf.PdfError` instead — both siblings of `PikepdfError`, neither a
    subclass of the other (checked directly against the installed pikepdf).
    Either way, "doesn't open with this bank's password" is the right
    reading: this parser isn't the match, try the next one or give up, not a
    crash.
    """
    try:
        with pikepdf.open(path, password=password):
            return True
    except pikepdf.PikepdfError:
        return False


def detect(path: Path) -> _Parser:
    """Return the registered parser that recognizes `path`'s content.

    Every parser with a fast, password-free `detect()` is tried first, in
    registration order; only if none of them match does the password-fallback
    pass run, trying each remaining parser's own `password_env` in turn (see
    the module docstring). A bank in that second pass is unreachable if its
    password env var isn't set to the right value — the same way a wrong
    `BCP_PDF_PASSWORD` surfaces once `parse()` itself is reached, just one
    step earlier here, since detecting *is* decrypting for this bank.

    Raises `UnrecognizedBankError` if none of them do.
    """
    for parser in _PARSERS:
        if parser.detect is not None and parser.detect(path):
            return parser
    for parser in _PARSERS:
        if parser.detect is None:
            password = os.environ.get(parser.password_env, "")
            if _decrypts(path, password):
                return parser
    raise UnrecognizedBankError(f"no parser recognizes {path.name}")


def parse(
    path: Path, *, user_id: str, file_sha256: str, password: str = ""
) -> list[Statement]:
    """Detect `path`'s bank and parse it into reconciled `Statement`s."""
    parser = detect(path)
    return parser.parse(
        path, user_id=user_id, file_sha256=file_sha256, password=password
    )
