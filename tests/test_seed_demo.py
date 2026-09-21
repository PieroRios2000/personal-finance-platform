"""`scripts/seed_demo.py`: artificial data for a demo dashboard (T33).

Pure generation is tested here; writing it to bronze is `bronze.write_statement`,
exercised by the live demo."""

from datetime import date

from ingestion.reconciliation import reconcile
from scripts import seed_demo

_TODAY = date(2026, 9, 21)


def test_every_demo_statement_reconciles_by_construction() -> None:
    for statement in seed_demo.demo_statements(_TODAY, user_id="demo"):
        reconcile(statement)  # raises if the movements do not add up to the balance


def test_only_closed_months_are_generated_and_they_are_consecutive() -> None:
    statements = seed_demo.demo_statements(_TODAY, user_id="demo")
    by_account: dict[str, list[date]] = {}
    for s in statements:
        by_account.setdefault(s.account_id, []).append(s.period_start)

    for starts in by_account.values():
        starts.sort()
        assert starts[-1] == date(
            2026, 8, 1
        )  # last closed month: the current is left out
        months = [(d.year, d.month) for d in starts]
        assert months == sorted(set(months))
        assert all(
            (b.year * 12 + b.month) - (a.year * 12 + a.month) == 1
            for a, b in zip(starts, starts[1:], strict=False)
        )


def test_the_demo_covers_the_cases_the_dashboard_shows() -> None:
    statements = seed_demo.demo_statements(_TODAY, user_id="demo")

    assert {s.account_kind for s in statements} == {"asset", "liability"}
    assert {s.currency for s in statements} == {"PEN", "USD"}
    assert {s.bank for s in statements} == {"BCP", "Scotiabank"}
    # a card charge is a positive amount there (ADR 0015), a payment negative
    card = [s for s in statements if s.account_kind == "liability"]
    amounts = [t.amount for s in card for t in s.transactions]
    assert any(a > 0 for a in amounts) and any(a < 0 for a in amounts)


def test_the_demo_is_deterministic_and_fictional() -> None:
    first = seed_demo.demo_statements(_TODAY, user_id="demo")
    second = seed_demo.demo_statements(_TODAY, user_id="demo")

    assert first == second
    assert all(s.user_id == "demo" for s in first)
    assert all("DEMO" in t.description for s in first for t in s.transactions)


def test_the_demo_funds_have_a_valuation_each_month() -> None:
    months = seed_demo.demo_investment_months(_TODAY, user_id="demo")

    assert months
    assert all(m.entries[-1].kind == "valorizacion" for m in months)
    assert max((m.year, m.month) for m in months) == (2026, 8)


def test_a_later_month_continues_the_same_history() -> None:
    """Running the demo next month must extend it, not restart it.

    Months both windows contain are identical, and every account's chain stays
    continuous (each statement opens where the previous one closed), or the continuity
    test would fail."""
    september = seed_demo.demo_statements(date(2026, 9, 21), user_id="demo")
    october = seed_demo.demo_statements(date(2026, 10, 2), user_id="demo")

    assert [s for s in october if s.period_start <= date(2026, 8, 1)] == [
        s for s in september if s.period_start >= date(2026, 2, 1)
    ]
    for statements in (september, october):
        by_account: dict[str, list] = {}
        for s in statements:
            by_account.setdefault(s.account_id, []).append(s)
        for chain in by_account.values():
            chain.sort(key=lambda s: s.period_start)
            assert all(
                a.closing_balance == b.opening_balance
                for a, b in zip(chain, chain[1:], strict=False)
            )


def test_the_fund_also_continues_across_windows() -> None:
    september = seed_demo.demo_investment_months(date(2026, 9, 21), user_id="demo")
    october = seed_demo.demo_investment_months(date(2026, 10, 2), user_id="demo")
    overlap = {(m.year, m.month): m for m in september}

    for month in october:
        if (month.year, month.month) in overlap:
            assert month == overlap[(month.year, month.month)]
