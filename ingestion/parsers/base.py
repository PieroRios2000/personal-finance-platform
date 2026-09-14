"""Shape every bank-specific parser module implements (T11).

`ingestion.dispatcher` (T12) uses `detect()` to pick the right parser for a PDF
by its content, never by its file name (ADR 0009), then calls `parse()` on the one
that recognizes it. `BankParser` documents that shape; a parser module (e.g.
`ingestion.parsers.bcp`) satisfies it by exposing matching module-level functions,
not a class — there's nothing stateful a parser needs to hold between calls.

`detect()` is optional (T18). It exists for a bank whose files carry a cheap,
password-free signature — BCP's `$BOP$` byte prefix. A bank with no such
signature (Scotiabank: its raw bytes start with a plain `%PDF-`) omits it and is
registered with `detect=None`, which puts it in the dispatcher's password
fallback pass instead; see `ingestion/dispatcher.py`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ingestion.schema import Statement


class BankParser(Protocol):
    """What a bank parser module must expose."""

    detect: Callable[[Path], bool]
    """True if this parser recognizes the PDF at `path`, from its content alone.

    Optional: a parser with no cheap, password-free signature omits this
    entirely (see the module docstring).
    """

    parse: Callable[..., list[Statement]]
    """Parse `path` into `Statement`s, each reconciled against its own totals.

    Signature: `parse(path, *, user_id, file_sha256, password="") -> list[Statement]`.
    Raises `ingestion.reconciliation.ReconciliationError` if the extracted
    transactions don't add up to what the statement declares, and `ValueError`
    if the PDF can't be read as this bank's statement at all.

    A list, because one PDF can hold more than one statement: a Scotiabank
    credit-card statement (T18) prints Soles and Dólares activity side by side,
    and `Statement` holds one `opening_balance`/`closing_balance` pair, not one
    per currency — so that file becomes two independently reconciled
    `Statement`s. BCP always returns exactly one. The list is never empty: a
    parser that can't produce a single statement raises instead, so a caller
    can safely read `statements[0]` for the file-level bank/account/period.
    """
