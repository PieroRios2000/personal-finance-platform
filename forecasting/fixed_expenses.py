"""Which recurring charges look fixed (T56, ADR 0048, spec section 4.1).

A pure rule over monthly totals per `(bank, description, currency)`: a charge present in
at least `MIN_MONTHS_SEEN` of the last `WINDOW_MONTHS` months is listed, and proposed as
fixed when its monthly totals barely move. It only *proposes*: the owner decides in the
plan workbook. The thresholds are a starting point to calibrate on the first real
export.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date

import numpy as np

WINDOW_MONTHS = 6
MIN_MONTHS_SEEN = 4
# Median absolute deviation as a share of the median monthly total.
MAX_SPREAD = 0.10


@dataclass(frozen=True)
class MonthlySpend:
    """One month's spending on a description; `month` is that month's first day."""

    bank: str
    description: str
    currency: str
    category: str
    month: date
    amount: float


@dataclass(frozen=True)
class Candidate:
    bank: str
    description: str
    currency: str
    category: str
    months_seen: int
    typical_amount: float
    proposed_kind: str
    note: str = ""


def _month_index(month: date) -> int:
    return month.year * 12 + month.month - 1


def detect_candidates(rows: Iterable[MonthlySpend]) -> list[Candidate]:
    """Recurring charges of the last six months in the data, fixed ones first."""
    rows = list(rows)
    if not rows:
        return []
    last = max(_month_index(r.month) for r in rows)
    first = last - WINDOW_MONTHS + 1

    totals: dict[tuple[str, str, str], dict[int, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    categories: dict[tuple[str, str, str], str] = {}
    for row in rows:
        index = _month_index(row.month)
        if index < first:
            continue
        key = (row.bank, row.description, row.currency)
        totals[key][index] += row.amount
        categories[key] = row.category

    candidates: list[Candidate] = []
    for key, by_month in totals.items():
        amounts = np.array([a for a in by_month.values() if a > 0])
        if len(amounts) < MIN_MONTHS_SEEN:
            continue
        median = float(np.median(amounts))
        spread = float(np.median(np.abs(amounts - median))) / median
        bank, description, currency = key
        candidates.append(
            Candidate(
                bank=bank,
                description=description,
                currency=currency,
                category=categories[key],
                months_seen=len(amounts),
                typical_amount=round(median, 2),
                proposed_kind="fixed" if spread <= MAX_SPREAD else "variable",
            )
        )
    return _with_currency_notes(sorted(candidates, key=_order))


def _order(candidate: Candidate) -> tuple[int, float, str, str, str]:
    return (
        candidate.proposed_kind != "fixed",
        -candidate.typical_amount,
        candidate.bank,
        candidate.description,
        candidate.currency,
    )


def _with_currency_notes(candidates: list[Candidate]) -> list[Candidate]:
    """A description in two currencies is listed once per currency; each says so."""
    currencies: dict[tuple[str, str], set[str]] = defaultdict(set)
    for c in candidates:
        currencies[(c.bank, c.description)].add(c.currency)
    noted: list[Candidate] = []
    for c in candidates:
        others = sorted(currencies[(c.bank, c.description)] - {c.currency})
        note = f"also seen in {', '.join(others)}" if others else ""
        noted.append(replace(c, note=note))
    return noted
