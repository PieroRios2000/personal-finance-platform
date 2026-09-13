"""BCP bank-statement parser (T11): turns a decrypted PDF into a reconciled Statement.

Column positions aren't hardcoded to one fixed layout: they're read from wherever
this specific PDF's own header row places FECHA/DESCRIPCION/CARGO/ABONO/SALDO, and
each row's words are then assigned to the nearest header to their left. T10's
synthetic fixture and a real BCP statement won't necessarily share exact pixel
positions, but they do share this column order (the same Spanish vocabulary
`scripts/inspect_pdf_layout.py`'s HEADERS leaves unmasked), so deriving the
boundaries from the header row itself is more robust than hardcoding one
fixture's coordinates. This is still provisional: it hasn't been checked against
a real masked layout dump yet (see T10's PR notes and the risk in tasks/plan.md).
"""

import io
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pdfplumber
import pikepdf

from ingestion.reconciliation import reconcile
from ingestion.schema import (
    Statement,
    Transaction,
    hash_account,
    last4_of,
    normalize_description,
)

# The real BCP export has this 5-byte marker before its %PDF- header (found by
# inspecting the owner's real file with scripts/inspect_pdf_layout.py, T9).
# pikepdf tolerates it either way, so parsing doesn't need to special-case it.
_BOP_PREFIX = b"$BOP$"

_HEADER_ROW = ("FECHA", "DESCRIPCION", "CARGO", "ABONO", "SALDO")
_ACCOUNT_RE = re.compile(r"CUENTA\s+NRO\.?\s+([\d\-]+)")
_PERIOD_RE = re.compile(
    r"PERIODO\s+DEL\s+(\d{2}/\d{2}/\d{4})\s+AL\s+(\d{2}/\d{2}/\d{4})"
)
_OPENING_RE = re.compile(r"SALDO\s+ANTERIOR\s+([\d,]+\.\d{2})")
_CLOSING_RE = re.compile(r"SALDO\s+ACTUAL\s+([\d,]+\.\d{2})")
_ROW_DATE_RE = re.compile(r"^\d{2}/\d{2}$")

Word = dict[str, Any]


def detect(path: Path) -> bool:
    """True if `path`'s raw bytes carry BCP's confirmed `$BOP$` prefix."""
    with path.open("rb") as handle:
        return handle.read(len(_BOP_PREFIX)) == _BOP_PREFIX


def _money(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _parse_date(text: str) -> date:
    day, month, year = (int(part) for part in text.split("/"))
    return date(year, month, day)


def _row_date(day_month: str, period_start: date, period_end: date) -> date:
    """A row only prints DD/MM; infer the year from the statement's own period."""
    day, month = (int(part) for part in day_month.split("/"))
    year = period_start.year if month >= period_start.month else period_end.year
    return date(year, month, day)


def _group_lines(words: list[Word]) -> list[list[Word]]:
    """Group words whose top edge is within 3 pt of each other into one line.

    Same grouping `scripts/inspect_pdf_layout.py` uses; kept as a small local
    copy rather than imported, since `scripts/` are standalone tools, not a
    library `ingestion` depends on.
    """
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and word["top"] - lines[-1][0]["top"] <= 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _find_header_columns(lines: list[list[Word]]) -> dict[str, float] | None:
    """Find the row containing all of `_HEADER_ROW` and return each one's x0."""
    for line in lines:
        texts = {word["text"] for word in line}
        if texts.issuperset(_HEADER_ROW):
            return {
                word["text"]: word["x0"] for word in line if word["text"] in _HEADER_ROW
            }
    return None


def _assign_columns(line: list[Word], columns: dict[str, float]) -> dict[str, str]:
    """Map each word in `line` to the nearest header column to its left."""
    boundaries = sorted(columns.items(), key=lambda item: item[1])
    cells: dict[str, list[str]] = {name: [] for name, _ in boundaries}
    for word in line:
        name = boundaries[0][0]
        for column_name, column_x in boundaries:
            if word["x0"] >= column_x - 5:
                name = column_name
        cells[name].append(word["text"])
    return {name: " ".join(words) for name, words in cells.items()}


def parse(
    path: Path, *, user_id: str, file_sha256: str, password: str = ""
) -> Statement:
    """Parse the BCP PDF at `path` into a `Statement`, reconciled against its own
    declared totals. Raises `ReconciliationError` if the numbers don't add up.
    """
    with pikepdf.open(path, password=password) as pdf:
        decrypted = io.BytesIO()
        pdf.save(decrypted)

    with pdfplumber.open(decrypted) as doc:
        full_text = "\n".join(page.extract_text() or "" for page in doc.pages)
        words: list[Word] = []
        for page in doc.pages:
            words.extend(page.extract_words())

    account_match = _ACCOUNT_RE.search(full_text)
    period_match = _PERIOD_RE.search(full_text)
    opening_match = _OPENING_RE.search(full_text)
    closing_match = _CLOSING_RE.search(full_text)
    if not (account_match and period_match and opening_match and closing_match):
        raise ValueError(
            "could not find the account number, period or balances in this "
            "BCP statement"
        )

    account_number = account_match[1]
    account_id = hash_account("BCP", account_number)
    account_last4 = last4_of(account_number)
    period_start = _parse_date(period_match[1])
    period_end = _parse_date(period_match[2])
    opening_balance = _money(opening_match[1])
    closing_balance = _money(closing_match[1])

    lines = _group_lines(words)
    columns = _find_header_columns(lines)
    if columns is None:
        raise ValueError(
            "could not find the FECHA/DESCRIPCION/CARGO/ABONO/SALDO header row"
        )

    transactions = []
    for line in lines:
        cells = _assign_columns(line, columns)
        row_date = cells.get("FECHA", "").strip()
        if not _ROW_DATE_RE.match(row_date):
            continue  # header row, or an info line like "CUENTA NRO. ..."

        charge = cells.get("CARGO", "").strip()
        credit = cells.get("ABONO", "").strip()
        if charge and credit:
            raise ValueError(f"row {row_date} has both a charge and a credit")
        if charge:
            amount = -_money(charge)
        elif credit:
            amount = _money(credit)
        else:
            continue  # a dated row with no amount isn't a movement

        transactions.append(
            Transaction(
                user_id=user_id,
                bank="BCP",
                account_id=account_id,
                account_last4=account_last4,
                date=_row_date(row_date, period_start, period_end),
                description=normalize_description(cells.get("DESCRIPCION", "")),
                amount=amount,
                currency="PEN",
                source_file_sha256=file_sha256,
            )
        )

    statement = Statement(
        user_id=user_id,
        bank="BCP",
        account_id=account_id,
        account_last4=account_last4,
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        transactions=transactions,
    )
    reconcile(statement)
    return statement
