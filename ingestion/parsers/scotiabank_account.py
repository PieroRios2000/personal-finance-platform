"""Scotiabank savings-account layout, the second one `scotiabank.parse` reads.

A Scotiabank card statement (`scotiabank.py`) and a savings-account statement
are different documents that share a bank and a password. This one was
calibrated against a masked layout dump of a real statement and then checked
against every real one the owner has (counts only, ADR 0004):

- The account is a line with `CUENTA` and a `000-0000000` number; `M.N. SOLES`
  or `M.E. DOLARES` on the same line gives the currency. The number is the
  account's identity and its last four digits are `account_last4`.
- The period is `01-ENE- 2026 Al 31-ENE-2026`: Spanish three-letter months and,
  after the first date, the year as a separate word.
- The header is two lines (`FECHA` / `FECHA VALOR`, then `CONCEPTO REFERENCIA
  CARGO ABONO SALDO`). Rows are `DD/MM` (processing), `DD/MM` (value date, the
  one kept, as for the other Scotiabank layout), a 3-digit code, the
  description, a reference, one of CARGO/ABONO, and the running SALDO. There is
  no year on a row: it comes from the period.
- Amounts are right-aligned, so a column is picked by the right edge of its
  header label, not the left one.
- A `Saldo Final al ...` line carrying only a balance opens the statement; a
  second one, with the CARGO total, the ABONO total and the closing balance,
  closes it. Those are declared by the bank, so `reconcile()` checks the
  balance and both totals for real (unlike the card layout).
- CARGO is money leaving (negative), ABONO money arriving (positive): the same
  sign convention as BCP, and the account is an `asset`.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Any

from ingestion.reconciliation import reconcile
from ingestion.schema import (
    Currency,
    Statement,
    Transaction,
    hash_account,
    normalize_description,
)

Word = dict[str, Any]

_ACCOUNT_NUMBER_RE = re.compile(r"^\d{3}-\d{7}$")
_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}$")
_ROW_DATE_RE = re.compile(r"^(\d{2})/(\d{2})$")
_CODE_RE = re.compile(r"^\d{3}$")
_PERIOD_RE = re.compile(
    r"(\d{2})-([A-Za-z]{3})-\s?(\d{4})\s+Al\s+(\d{2})-([A-Za-z]{3})-(\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("ENE",),
            ("FEB",),
            ("MAR",),
            ("ABR",),
            ("MAY",),
            ("JUN",),
            ("JUL",),
            ("AGO",),
            ("SET", "SEP"),
            ("OCT",),
            ("NOV",),
            ("DIC",),
        ],
        start=1,
    )
    for name in names
}
_MONEY_COLUMNS = ("CARGO", "ABONO", "SALDO")


def _amount(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _month(text: str) -> int:
    try:
        return _MONTHS[text.upper()]
    except KeyError:
        raise ValueError("unrecognized month in the statement period") from None


def _find_period(lines: list[list[Word]]) -> tuple[date, date] | None:
    for line in lines:
        match = _PERIOD_RE.search(" ".join(w["text"] for w in line))
        if match:
            return (
                date(int(match[3]), _month(match[2]), int(match[1])),
                date(int(match[6]), _month(match[5]), int(match[4])),
            )
    return None


def _find_account(lines: list[list[Word]]) -> tuple[str, Currency] | None:
    """The account number and currency from the `CUENTA ...` line."""
    for line in lines:
        texts = [w["text"] for w in line]
        upper = {t.upper() for t in texts}
        number = next((t for t in texts if _ACCOUNT_NUMBER_RE.match(t)), None)
        if "CUENTA" not in upper or number is None:
            continue
        if "SOLES" in upper:
            return number, "PEN"
        if upper & {"DOLARES", "DÓLARES"}:
            return number, "USD"
    return None


def _find_header(lines: list[list[Word]]) -> dict[str, float] | None:
    """Right edge of the CARGO/ABONO/SALDO labels (amounts are right-aligned)
    and left edge of REFERENCIA (where the description ends)."""
    for line in lines:
        by_text = {w["text"].upper(): w for w in line}
        if all(name in by_text for name in (*_MONEY_COLUMNS, "CONCEPTO")):
            columns = {name: by_text[name]["x1"] for name in _MONEY_COLUMNS}
            columns["REFERENCIA_X0"] = by_text["REFERENCIA"]["x0"]
            return columns
    return None


def _money_by_column(line: list[Word], columns: dict[str, float]) -> dict[str, Decimal]:
    """Each amount on the line, under the header label nearest its right edge."""
    found: dict[str, Decimal] = {}
    for word in line:
        if not _AMOUNT_RE.match(word["text"]):
            continue
        name = min(_MONEY_COLUMNS, key=lambda c: abs(columns[c] - word["x1"]))
        found[name] = _amount(word["text"])
    return found


def _row_date(day_month: str, period: tuple[date, date]) -> date:
    """A row prints no year: the one whose date falls inside the period."""
    match = _ROW_DATE_RE.match(day_month)
    assert match
    day, month = int(match[1]), int(match[2])
    for year in dict.fromkeys((period[0].year, period[1].year)):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if period[0] <= candidate <= period[1]:
            return candidate
    raise ValueError("a row's date falls outside the statement period")


def parse_pages(
    pages: list[list[list[Word]]], *, user_id: str, file_sha256: str
) -> list[Statement] | None:
    """Parse already-grouped lines (one list per page) as a savings-account
    statement. `None` when the PDF isn't this layout, so the caller can report
    it; `ValueError`/`ReconciliationError` when it is but doesn't add up."""
    lines = [line for page in pages for line in page]
    columns = _find_header(lines)
    if columns is None:
        return None

    account = _find_account(lines)
    period = _find_period(lines)
    if account is None or period is None:
        raise ValueError(
            "could not find the account number, currency or period in this "
            "Scotiabank account statement"
        )
    number, currency = account
    account_id = hash_account("Scotiabank", number)

    balances: list[dict[str, Decimal]] = []
    transactions: list[Transaction] = []
    for line in lines:
        texts = [w["text"] for w in line]
        lowered = {t.lower() for t in texts}
        if {"saldo", "final", "al"} <= lowered:
            balances.append(_money_by_column(line, columns))
            continue
        dates = [t for t in texts[:2] if _ROW_DATE_RE.match(t)]
        if not dates:
            continue
        amounts = _money_by_column(line, columns)
        movement = {k: v for k, v in amounts.items() if k != "SALDO"}
        if len(movement) != 1:
            raise ValueError(
                f"row {dates[0]} does not have exactly one CARGO or ABONO amount"
            )
        description_words = [
            w["text"]
            for w in line
            if w["x0"] < columns["REFERENCIA_X0"]
            and not _ROW_DATE_RE.match(w["text"])
            and not _CODE_RE.match(w["text"])
        ]
        ((column, value),) = movement.items()
        transactions.append(
            Transaction(
                user_id=user_id,
                bank="Scotiabank",
                account_id=account_id,
                account_last4=number[-4:],
                date=_row_date(dates[-1], period),
                description=normalize_description(" ".join(description_words)),
                amount=-value if column == "CARGO" else value,
                currency=currency,
                source_file_sha256=file_sha256,
            )
        )

    if len(balances) < 2 or "SALDO" not in balances[0]:
        raise ValueError("could not find the opening and closing 'Saldo Final' lines")
    closing = balances[-1]
    if not {"CARGO", "ABONO", "SALDO"} <= closing.keys():
        raise ValueError("the closing 'Saldo Final' line has no totals")

    statement = Statement(
        user_id=user_id,
        bank="Scotiabank",
        account_id=account_id,
        account_last4=number[-4:],
        period_start=period[0],
        period_end=period[1],
        opening_balance=balances[0]["SALDO"],
        closing_balance=closing["SALDO"],
        declared_charges_total=closing["CARGO"],
        declared_credits_total=closing["ABONO"],
        account_kind="asset",
        currency=currency,
        transactions=transactions,
    )
    reconcile(statement)
    return [statement]
