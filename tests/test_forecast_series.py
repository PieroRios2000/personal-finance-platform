"""`forecasting.series`: monthly spend per (category, currency) over closed months only
(T58, ADR 0048, spec 4.2). Every row is synthetic."""

from datetime import date

from forecasting.fixed_expenses import MonthlySpend
from forecasting.series import TOTAL, build_series

OPEN = date(2026, 10, 1)  # the current, still open month


def _row(
    month: date,
    amount: float,
    *,
    description: str = "planted shop",
    category: str = "Alimentacion",
    currency: str = "PEN",
    bank: str = "BCP",
) -> MonthlySpend:
    return MonthlySpend(bank, description, currency, category, month, amount)


def test_the_open_month_is_never_in_a_series() -> None:
    rows = [_row(date(2026, 8, 1), 10), _row(date(2026, 9, 1), 20), _row(OPEN, 999)]

    series = build_series(rows, first_open_month=OPEN, excluded=set())

    food = series[("Alimentacion", "PEN")]
    assert food.months[-1] == date(2026, 9, 1)
    assert food.values.tolist() == [10, 20]


def test_a_month_without_spending_is_a_real_zero_after_the_first_data() -> None:
    rows = [
        _row(date(2026, 6, 1), 10),
        _row(date(2026, 8, 1), 30, category="Salud", description="planted clinic"),
        _row(date(2026, 9, 1), 50),
    ]

    series = build_series(rows, first_open_month=OPEN, excluded=set())

    assert series[("Alimentacion", "PEN")].values.tolist() == [10, 0, 0, 50]
    assert series[("Salud", "PEN")].values.tolist() == [0, 0, 30, 0]
    assert series[("Salud", "PEN")].months[0] == date(2026, 6, 1)


def test_months_before_the_users_history_in_a_currency_are_not_zeros() -> None:
    rows = [
        _row(date(2026, 3, 1), 5, currency="PEN"),
        _row(date(2026, 8, 1), 7, currency="USD", description="planted saas"),
        _row(date(2026, 9, 1), 7, currency="USD", description="planted saas"),
    ]

    series = build_series(rows, first_open_month=OPEN, excluded=set())

    assert len(series[("Alimentacion", "PEN")].values) == 7
    assert series[("Alimentacion", "USD")].values.tolist() == [7, 7]


def test_currencies_are_never_added_together() -> None:
    rows = [
        _row(date(2026, 9, 1), 100, currency="PEN"),
        _row(date(2026, 9, 1), 3, currency="USD"),
    ]

    series = build_series(rows, first_open_month=OPEN, excluded=set())

    assert series[(TOTAL, "PEN")].values.tolist() == [100]
    assert series[(TOTAL, "USD")].values.tolist() == [3]


def test_fixed_and_ignored_charges_leave_the_variable_series() -> None:
    rows = [
        _row(date(2026, 8, 1), 1000, description="planted rent", category="Vivienda"),
        _row(date(2026, 9, 1), 1000, description="planted rent", category="Vivienda"),
        _row(date(2026, 8, 1), 40),
        _row(date(2026, 9, 1), 60),
    ]

    series = build_series(
        rows, first_open_month=OPEN, excluded={("BCP", "planted rent", "PEN")}
    )

    assert ("Vivienda", "PEN") not in series
    assert series[(TOTAL, "PEN")].values.tolist() == [40, 60]


def test_the_total_is_the_sum_of_the_categories_each_month() -> None:
    rows = [
        _row(date(2026, 8, 1), 10),
        _row(date(2026, 8, 1), 5, category="Salud", description="planted clinic"),
        _row(date(2026, 9, 1), 20),
    ]

    series = build_series(rows, first_open_month=OPEN, excluded=set())

    assert series[(TOTAL, "PEN")].values.tolist() == [15, 20]


def test_no_closed_month_gives_no_series() -> None:
    assert build_series([_row(OPEN, 5)], first_open_month=OPEN, excluded=set()) == {}
