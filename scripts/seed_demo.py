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
from datetime import date, timedelta
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
# The history starts at a fixed month, so the balance every account opens with in any
# month is the same whenever the demo is run: running it again next month extends the
# history (the overlapping months are identical) instead of restarting it.
_ANCHOR = date(2024, 1, 1)


def _closed_months(today: date, first: date = _ANCHOR) -> list[date]:
    """The first day of every closed month from `first` to the one before today's."""
    months = []
    month = first
    current = today.replace(day=1)
    while month < current:
        months.append(month)
        month = (month + timedelta(days=32)).replace(day=1)
    return months


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
    items: list[tuple[int, str, Decimal]],
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
            amount=amount,
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
    """The last eight closed months of every demo account, oldest first.

    Every amount depends only on the month, and every balance chain starts at the fixed
    anchor, so the result is deterministic and consistent across runs and months."""
    statements = []
    checking, card, dollars = Decimal("1500.00"), Decimal("800.00"), Decimal("300.00")
    for month in _closed_months(today):
        groceries = Decimal(380 + 15 * (month.month % 4))
        charges = (
            Decimal(640 + 20 * (month.month % 3)),
            Decimal(410 + 10 * (month.month % 5)),
        )
        payment = charges[0] + charges[1]  # the card is paid in full each month
        checking_statement = _statement(
            user_id=user_id,
            bank="BCP",
            name="bcp-soles",
            last4="0001",
            kind="asset",
            currency="PEN",
            month=month,
            opening=checking,
            items=[
                (2, "SALARY ACME", Decimal("3200.00")),
                (3, "RENT", Decimal("-900.00")),
                (10, f"GROCERIES {month:%b}", -groceries),
                (14, "UTILITIES", Decimal("-180.50")),
                (18, "TRANSFER TO FUND", Decimal("-300.00")),
                (20, "CARD PAYMENT", -payment),
            ],
        )
        card_statement = _statement(
            user_id=user_id,
            bank="Scotiabank",
            name="card-soles",
            last4="0002",
            kind="liability",
            currency="PEN",
            month=month,
            opening=card,
            items=[
                (5, "SHOP ONE", charges[0]),
                (12, "SHOP TWO", charges[1]),
                (21, "PAYMENT RECEIVED", -payment),
            ],
        )
        dollars_statement = _statement(
            user_id=user_id,
            bank="BCP",
            name="bcp-dollars",
            last4="0003",
            kind="asset",
            currency="USD",
            month=month,
            opening=dollars,
            items=[
                (4, "DEPOSIT", Decimal("150.00")),
                (16, "ONLINE STORE", Decimal("-45.00")),
            ],
        )
        checking = checking_statement.closing_balance
        card = card_statement.closing_balance
        dollars = dollars_statement.closing_balance
        statements += [checking_statement, card_statement, dollars_statement]
    return [s for s in statements if s.period_start >= _window_start(today, _MONTHS)]


def _window_start(today: date, count: int) -> date:
    return _closed_months(today)[-count]


def demo_investment_months(today: date, user_id: str = "demo") -> list[InvestmentMonth]:
    """One fund, a contribution and a month-end valuation each month (about +1%),
    the balance chain starting at the same fixed anchor as the statements."""
    balance = Decimal("2000.00")
    months = []
    for month in _closed_months(today):
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
    return months[-_FUND_MONTHS:]


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
