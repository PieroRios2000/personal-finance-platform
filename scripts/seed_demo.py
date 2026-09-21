"""Artificial data for a demo dashboard (T33): eight closed months of a fictional user.

    uv run python -m scripts.seed_demo [--user demo]

Writes straight to bronze (no PDFs): a BCP checking account in soles (salary, rent,
groceries, a card payment, a transfer to a fund), a Scotiabank credit card (charges are
positive, payments negative, ADR 0015), a small BCP account in dollars, and one
investment fund with a month-end valuation each month. Everything is fictional and
marked `DEMO`, every statement reconciles by construction, and only closed months are
generated (the current one is left out, like the dashboard does). Running it twice
writes nothing new. Then `dbt build` and the dashboard show the platform working before
any real statement is loaded.
"""

import argparse
import calendar
import hashlib
import os
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from ingestion.schema import (
    Currency,
    InvestmentEntry,
    InvestmentMonth,
    Statement,
    Transaction,
)
from lakehouse import bronze

_MONTHS = 8
_FUND_MONTHS = 6


def _closed_months(today: date, count: int) -> list[date]:
    """The first day of each of the last `count` closed months, oldest first."""
    first = today.replace(day=1)
    months = []
    for _ in range(count):
        first = (first.replace(day=1) - date.resolution).replace(day=1)
        months.append(first)
    return months[::-1]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _statement(
    *,
    user_id: str,
    bank: str,
    name: str,
    last4: str,
    kind: str,
    currency: Currency,
    month: date,
    opening: Decimal,
    items: list[tuple[int, str, str]],
) -> Statement:
    account_id = _sha(f"demo-{name}")
    file_sha = _sha(f"demo-{name}-{month}")
    transactions = [
        Transaction(
            user_id=user_id,
            bank=bank,
            account_id=account_id,
            account_last4=last4,
            date=month.replace(day=day),
            description=f"DEMO {description}",
            amount=Decimal(amount),
            currency=currency,
            source_file_sha256=file_sha,
        )
        for day, description, amount in items
    ]
    return Statement(
        user_id=user_id,
        bank=bank,
        account_id=account_id,
        account_last4=last4,
        period_start=month,
        period_end=month.replace(day=calendar.monthrange(month.year, month.month)[1]),
        opening_balance=opening,
        closing_balance=opening + sum((t.amount for t in transactions), Decimal(0)),
        account_kind="liability" if kind == "liability" else "asset",
        currency=currency,
        transactions=transactions,
    )


def demo_statements(today: date, user_id: str = "demo") -> list[Statement]:
    """Every demo statement, oldest first. Deterministic for a given `today`."""
    statements = []
    checking, card, dollars = Decimal("1500.00"), Decimal("800.00"), Decimal("300.00")
    for index, month in enumerate(_closed_months(today, _MONTHS)):
        groceries = 380 + 15 * (index % 4)
        charges = (640 + 20 * (index % 3), 410 + 10 * (index % 5))
        statement = _statement(
            user_id=user_id,
            bank="BCP",
            name="bcp-soles",
            last4="0001",
            kind="asset",
            currency="PEN",
            month=month,
            opening=checking,
            items=[
                (2, "SALARY ACME", "3200.00"),
                (3, "RENT", "-900.00"),
                (10, f"GROCERIES {index}", f"-{groceries}.00"),
                (14, "UTILITIES", "-180.50"),
                (18, "TRANSFER TO FUND", "-300.00"),
                (20, "CARD PAYMENT", "-1100.00"),
            ],
        )
        statements.append(statement)
        checking = statement.closing_balance
        statement = _statement(
            user_id=user_id,
            bank="Scotiabank",
            name="card-soles",
            last4="0002",
            kind="liability",
            currency="PEN",
            month=month,
            opening=card,
            items=[
                (5, "SHOP ONE", f"{charges[0]}.00"),
                (12, "SHOP TWO", f"{charges[1]}.00"),
                (21, "PAYMENT RECEIVED", "-1100.00"),
            ],
        )
        statements.append(statement)
        card = statement.closing_balance
        statement = _statement(
            user_id=user_id,
            bank="BCP",
            name="bcp-dollars",
            last4="0003",
            kind="asset",
            currency="USD",
            month=month,
            opening=dollars,
            items=[(4, "DEPOSIT", "150.00"), (16, "ONLINE STORE", "-45.00")],
        )
        statements.append(statement)
        dollars = statement.closing_balance
    return statements


def demo_investment_months(today: date, user_id: str = "demo") -> list[InvestmentMonth]:
    """One fund, a contribution and a month-end valuation each month (about +1%)."""
    balance = Decimal("2000.00")
    months = []
    for month in _closed_months(today, _FUND_MONTHS):
        contribution = Decimal("300.00")
        after_contribution = balance + contribution
        balance = (after_contribution * Decimal("1.01")).quantize(Decimal("0.01"))
        last_day = calendar.monthrange(month.year, month.month)[1]
        months.append(
            InvestmentMonth(
                user_id=user_id,
                place="Fondo DEMO",
                currency="PEN",
                year=month.year,
                month=month.month,
                month_key=_sha(f"demo-fund-{month}"),
                entries=[
                    InvestmentEntry(
                        date=month.replace(day=5),
                        kind="aporte",
                        amount=contribution,
                        balance=after_contribution,
                        position=2,
                    ),
                    InvestmentEntry(
                        date=month.replace(day=last_day),
                        kind="valorizacion",
                        amount=Decimal("0"),
                        balance=balance,
                        position=3,
                    ),
                ],
            )
        )
    return months


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER") or "demo")
    args = parser.parse_args(argv)

    today = date.today()
    written = 0
    for statement in demo_statements(today, args.user):
        sha = statement.transactions[0].source_file_sha256
        if not bronze.is_ingested(args.user, sha):
            bronze.write_statement(statement, sha)
            written += 1
    months = demo_investment_months(today, args.user)
    for month in months:
        bronze.replace_investment_month(month)
    print(
        f"demo data for user {args.user!r}: {written} statement(s) written, "
        f"{len(months)} fund month(s). Now: dbt build."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
