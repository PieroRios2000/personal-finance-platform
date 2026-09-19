"""Reads the manual Excel's `Ahorros` sheet (savings accounts, Banco Ripley
first) into the same `Statement`s the PDF parsers produce, so they flow through
bronze, silver and gold and are reconciled the same way.

Banco Ripley gives no statements, so the owner types the movements (ADR 0027,
docs/manual-data.md). Rules that follow from that:

- One statement per account, currency and calendar month. A month with no
  movements is a `cierre de mes` row (amount 0): a balance marker, not a
  transaction (`Transaction` rejects a zero amount, ADR 0005).
- Each row's `saldo_final` must be the previous row's plus its `monto`. That is
  the reconciliation for this source: a mistyped balance or amount is reported,
  not absorbed. Between months, dbt's continuity test checks the same thing.
- A month's identity (the `file_sha256` bronze keys it on) comes from user,
  account, currency and month, **not** from its content, so loading a corrected
  workbook *replaces* that month (`bronze.replace_statement`) and loading the
  same one again changes nothing.
- Problems are reported as row numbers and column names, never as values.
- The account is identified by its name in the sheet (there is no account
  number to hash), and `account_last4` is `0000`.

`ingestion` never imports `lakehouse` (only `ingestion.cli` does): this module
returns statements and the CLI writes them.
"""

import calendar
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ingestion.reconciliation import reconcile
from ingestion.schema import (
    Currency,
    Statement,
    Transaction,
    hash_account,
    normalize_description,
)

SAVINGS_COLUMNS = ("cuenta", "fecha", "descripcion", "monto", "moneda", "saldo_final")
SHEET = "Ahorros"
_EXAMPLE_PREFIX = "EJEMPLO"
_MONTH_END = "cierre de mes"


@dataclass(frozen=True)
class Entry:
    statement: Statement
    file_sha256: str


@dataclass
class SavingsImport:
    entries: list[Entry] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    missing_months: int = 0


@dataclass(frozen=True)
class _Row:
    number: int
    account: str
    day: date
    description: str
    amount: Decimal
    currency: Currency
    balance: Decimal


def _money(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(round(float(value), 2)))


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _parse_rows(raw: list[tuple[int, tuple[Any, ...]]]) -> tuple[list[_Row], list[str]]:
    rows: list[_Row] = []
    problems: list[str] = []
    for number, cells in raw:
        account, when, description, amount, currency, balance = cells[:6]
        day, value, closing = _day(when), _money(amount), _money(balance)
        found: list[str] = []
        if not (isinstance(account, str) and account.strip()):
            found.append("cuenta is empty")
        if day is None:
            found.append("fecha is not a date")
        if not (isinstance(description, str) and description.strip()):
            found.append("descripcion is empty")
        if value is None:
            found.append("monto is not a number")
        if currency not in ("PEN", "USD"):
            found.append("moneda must be PEN or USD")
        if closing is None:
            found.append("saldo_final is not a number")
        if found:
            problems += [f"{SHEET} row {number}: {message}" for message in found]
            continue
        assert day is not None and value is not None and closing is not None
        rows.append(
            _Row(
                number,
                str(account).strip(),
                day,
                str(description).strip(),
                value,
                "PEN" if currency == "PEN" else "USD",
                closing,
            )
        )
    return rows, problems


def _identity(
    user_id: str, account_id: str, currency: str, year: int, month: int
) -> str:
    key = f"manual-excel|{user_id}|{account_id}|{currency}|{year}-{month:02d}"
    return hashlib.sha256(key.encode()).hexdigest()


def _months_between(first: tuple[int, int], last: tuple[int, int]) -> int:
    return (last[0] - first[0]) * 12 + last[1] - first[1] + 1


def _problem_order(problem: str) -> tuple[int, str]:
    """By row number when the problem names one, others first."""
    if "row " in problem:
        return int(problem.split("row ")[1].split(":")[0]), problem
    return 0, problem


def read_savings(path: Path, *, user_id: str) -> SavingsImport:
    result = SavingsImport()
    workbook = load_workbook(path, data_only=True)
    if SHEET not in workbook.sheetnames:
        result.problems.append(f"the workbook has no '{SHEET}' sheet")
        return result
    sheet = workbook[SHEET]
    header = tuple(c.value for c in sheet[1])
    if header[: len(SAVINGS_COLUMNS)] != SAVINGS_COLUMNS:
        result.problems.append(f"{SHEET}: the columns are not the template's")
        return result

    raw = [
        (index, tuple(row))
        for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2)
        if any(v is not None for v in row)
    ]
    examples = sum(
        1
        for _, cells in raw
        if isinstance(cells[0], str) and cells[0].startswith(_EXAMPLE_PREFIX)
    )
    if examples:
        result.problems.append(
            f"{SHEET}: {examples} example row(s) are still in the sheet (EJEMPLO)"
        )
        return result

    rows, problems = _parse_rows(raw)
    result.problems += problems
    groups: dict[tuple[str, Currency], list[_Row]] = {}
    for row in rows:
        groups.setdefault((row.account, row.currency), []).append(row)

    statements: list[Entry] = []
    for (account, currency), group in groups.items():
        group = sorted(group, key=lambda r: r.day)  # stable: sheet order within a day
        previous: Decimal | None = None
        broken = False
        for row in group:
            if previous is not None and row.balance != previous + row.amount:
                result.problems.append(
                    f"{SHEET} row {row.number}: "
                    "the balance does not follow the previous one"
                )
                broken = True
            previous = row.balance
        if broken:
            continue
        account_id = hash_account(account, account)
        by_month: dict[tuple[int, int], list[_Row]] = {}
        for row in group:
            by_month.setdefault((row.day.year, row.day.month), []).append(row)
        result.missing_months += _months_between(min(by_month), max(by_month)) - len(
            by_month
        )
        for (year, month), month_rows in sorted(by_month.items()):
            sha = _identity(user_id, account_id, currency, year, month)
            first, last = month_rows[0], month_rows[-1]
            statement = Statement(
                user_id=user_id,
                bank=account,
                account_id=account_id,
                account_last4="0000",
                period_start=date(year, month, 1),
                period_end=date(year, month, calendar.monthrange(year, month)[1]),
                opening_balance=first.balance - first.amount,
                closing_balance=last.balance,
                account_kind="asset",
                currency=currency,
                transactions=[
                    Transaction(
                        user_id=user_id,
                        bank=account,
                        account_id=account_id,
                        account_last4="0000",
                        date=r.day,
                        description=normalize_description(r.description),
                        amount=r.amount,
                        currency=currency,
                        source_file_sha256=sha,
                    )
                    for r in month_rows
                    if r.amount != 0
                ],
            )
            reconcile(statement)
            statements.append(Entry(statement, sha))

    result.problems.sort(
        key=lambda p: (int(p.split("row ")[1].split(":")[0]) if "row " in p else 0, p)
    )
    if not result.problems:
        result.entries = statements
    return result
