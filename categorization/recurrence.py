"""Point-in-time recurrence features for the classifier experiment (T63, ADR 0048
follow-up): how often a merchant showed up in earlier months and how steady its
monthly total was. Pure functions, no I/O.

Every feature of a row uses only months strictly before the row's own month, so a
later statement can never change what an earlier row "knew". A merchant is
`(bank, description with digit runs collapsed)`, the same grouping the
cross-validation uses (`categorization.model._merchant_group`).
"""

import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from categorization.model import _merchant_group

Merchant = tuple[str, str]


@dataclass(frozen=True)
class Occurrence:
    bank: str
    description: str
    month: date
    amount: float


@dataclass(frozen=True)
class Recurrence:
    """`rate` and `amount_spread` are `None` when there is nothing to compute them
    from (no prior month, or fewer than two prior months for the spread)."""

    months_seen: int
    rate: float | None
    amount_spread: float | None


def merchant_key(bank: str, description: str) -> Merchant:
    return bank, _merchant_group(description)


def _index(month: date) -> int:
    return month.year * 12 + month.month - 1


def _spread(totals: list[float]) -> float | None:
    if len(totals) < 2:
        return None
    median = statistics.median(totals)
    if median == 0:
        return None
    return statistics.median(abs(total - median) for total in totals) / median


def recurrence_features(
    occurrences: Sequence[Occurrence], window: int = 12
) -> list[Recurrence]:
    """One `Recurrence` per occurrence, in the same order. `window` is how many
    months back count; `rate` is months seen over the months of history the dataset
    has before the row (capped at `window`)."""
    totals: dict[Merchant, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for occurrence in occurrences:
        key = merchant_key(occurrence.bank, occurrence.description)
        totals[key][_index(occurrence.month)] += abs(occurrence.amount)
    first = min((_index(o.month) for o in occurrences), default=0)

    features = []
    for occurrence in occurrences:
        here = _index(occurrence.month)
        history = totals[merchant_key(occurrence.bank, occurrence.description)]
        prior = [t for m, t in sorted(history.items()) if here - window <= m < here]
        available = min(window, here - first)
        features.append(
            Recurrence(
                months_seen=len(prior),
                rate=len(prior) / available if available else None,
                amount_spread=_spread(prior),
            )
        )
    return features


def kind_by_merchant(plan: Iterable[tuple[str, str, str]]) -> dict[Merchant, str]:
    """`{merchant: kind}` from `(bank, description, kind)` plan rows; a merchant that
    is not in the plan is simply absent."""
    return {merchant_key(bank, description): kind for bank, description, kind in plan}
