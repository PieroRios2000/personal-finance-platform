"""Picks the right bank parser for a PDF by its content (T12), never its file
name (ADR 0009).

Each registered parser is a plain module (`ingestion.parsers.bcp`, and eventually
`ingestion.parsers.scotiabank`, T18) exposing `detect`/`parse` functions matching
`ingestion.parsers.base.BankParser`. A module can't be typed directly against that
Protocol (mypy doesn't structurally match a module against attribute Protocols),
so each one is wrapped here in a small `_Parser` tuple instead, which also carries
the environment variable holding that bank's PDF password.
"""

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from ingestion.parsers import bcp
from ingestion.schema import Statement


class _Parser(NamedTuple):
    bank: str
    password_env: str
    detect: Callable[[Path], bool]
    parse: Callable[..., Statement]


_PARSERS: tuple[_Parser, ...] = (
    _Parser("BCP", "BCP_PDF_PASSWORD", bcp.detect, bcp.parse),
)


class UnrecognizedBankError(ValueError):
    """No registered parser recognizes this PDF."""


def detect(path: Path) -> _Parser:
    """Return the registered parser that recognizes `path`'s content.

    Raises `UnrecognizedBankError` if none of them do.
    """
    for parser in _PARSERS:
        if parser.detect(path):
            return parser
    raise UnrecognizedBankError(f"no parser recognizes {path.name}")


def parse(
    path: Path, *, user_id: str, file_sha256: str, password: str = ""
) -> Statement:
    """Detect `path`'s bank and parse it into a reconciled `Statement`."""
    parser = detect(path)
    return parser.parse(
        path, user_id=user_id, file_sha256=file_sha256, password=password
    )
