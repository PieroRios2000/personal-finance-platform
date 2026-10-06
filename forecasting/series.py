"""Monthly variable spending per (category, currency) over closed months (T58, ADR 0048,
spec 4.2).

Zero-filled between the first month the user has any data in a currency and the last
closed month (a category absent in a month is a real zero; months before the history are
not). Fixed and ignored charges leave the series: the plan forecasts the fixed ones as
their expected amount. Currencies are never added together. `TOTAL` is the sum of the
variable categories of one currency, forecast on its own so the scenarios do not assume
every category errs the same way in the same month.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import numpy as np

from forecasting.fixed_expenses import MonthlySpend

TOTAL = "Total"


@dataclass(frozen=True, eq=False)
class Series:
    category: str
    currency: str
    months: tuple[date, ...]
    values: np.ndarray


def add_months(month: date, count: int) -> date:
    return _month(_index(month) + count)


def _index(month: date) -> int:
    return month.year * 12 + month.month - 1


def _month(index: int) -> date:
    return date(index // 12, index % 12 + 1, 1)


def build_series(
    rows: Iterable[MonthlySpend],
    *,
    first_open_month: date,
    excluded: set[tuple[str, str, str]],
) -> dict[tuple[str, str], Series]:
    """Series keyed by (category, currency), plus a (`TOTAL`, currency) per currency.
    `first_open_month` is the first day of the current month: it and later are dropped.
    `excluded` holds the (bank, description, currency) of fixed and ignored items."""
    last = _index(first_open_month) - 1
    closed = [row for row in rows if _index(row.month) <= last]
    first: dict[str, int] = {}
    for row in closed:
        first[row.currency] = min(first.get(row.currency, last), _index(row.month))

    sums: dict[tuple[str, str], dict[int, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    for row in closed:
        if (row.bank, row.description, row.currency) not in excluded:
            sums[(row.category, row.currency)][_index(row.month)] += row.amount

    series: dict[tuple[str, str], Series] = {}
    for currency, start in first.items():
        months = tuple(_month(i) for i in range(start, last + 1))
        total = np.zeros(len(months))
        for (category, cur), by_month in sums.items():
            if cur != currency:
                continue
            values = np.array([by_month.get(i, 0.0) for i in range(start, last + 1)])
            total += values
            series[(category, currency)] = Series(category, currency, months, values)
        series[(TOTAL, currency)] = Series(TOTAL, currency, months, total)
    return dict(sorted(series.items()))
