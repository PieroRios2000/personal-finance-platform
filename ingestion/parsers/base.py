"""Shape every bank-specific parser module implements (T11).

`ingestion.dispatcher` (T12) will use `detect()` to pick the right parser for a PDF
by its content, never by its file name (ADR 0009), then call `parse()` on the one
that recognizes it. `BankParser` documents that shape; a parser module (e.g.
`ingestion.parsers.bcp`) satisfies it by exposing matching module-level functions,
not a class — there's nothing stateful a parser needs to hold between calls.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ingestion.schema import Statement


class BankParser(Protocol):
    """What a bank parser module must expose."""

    detect: Callable[[Path], bool]
    """True if this parser recognizes the PDF at `path`, from its content alone."""

    parse: Callable[..., Statement]
    """Parse `path` into a `Statement`, reconciled against its own declared totals.

    Signature: `parse(path, *, user_id, file_sha256, password="") -> Statement`.
    Raises `ingestion.reconciliation.ReconciliationError` if the extracted
    transactions don't add up to what the statement declares.
    """
