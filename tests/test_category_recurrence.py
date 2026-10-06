"""Tests for categorization.recurrence: point-in-time recurrence features for the
classifier experiment (T63, ADR 0048 follow-up). All data is synthetic."""

from datetime import date

import pytest

from categorization import recurrence
from categorization.recurrence import Occurrence


def _month(index: int) -> date:
    year, month = divmod(index, 12)
    return date(2025 + year, month + 1, 1)


def _monthly(
    description: str, count: int, amount: float = 50.0, bank: str = "BCP"
) -> list[Occurrence]:
    return [Occurrence(bank, description, _month(i), amount) for i in range(count)]


def test_a_monthly_charge_has_full_recurrence_and_no_spread() -> None:
    rows = _monthly("NETFLIX.COM", 6)

    features = recurrence.recurrence_features(rows)

    assert features[5].months_seen == 5
    assert features[5].rate == pytest.approx(1.0)
    assert features[5].amount_spread == pytest.approx(0.0)


def test_the_first_month_has_no_history_at_all() -> None:
    features = recurrence.recurrence_features(_monthly("NETFLIX.COM", 3))

    assert features[0].months_seen == 0
    assert features[0].rate is None
    assert features[0].amount_spread is None


def test_one_prior_month_gives_a_rate_but_no_spread() -> None:
    features = recurrence.recurrence_features(_monthly("NETFLIX.COM", 2))

    assert features[1].months_seen == 1
    assert features[1].rate == pytest.approx(1.0)
    assert features[1].amount_spread is None


def test_a_later_month_never_changes_an_earlier_row() -> None:
    short = _monthly("NETFLIX.COM", 4)
    longer = [*short, Occurrence("BCP", "NETFLIX.COM", _month(4), 9999.0)]

    before = recurrence.recurrence_features(short)
    after = recurrence.recurrence_features(longer)

    assert after[:4] == before


def test_rate_is_the_share_of_available_months_the_merchant_appeared_in() -> None:
    rows = [
        Occurrence("BCP", "OTHER", _month(0), 10.0),
        Occurrence("BCP", "RARE", _month(1), 10.0),
        Occurrence("BCP", "OTHER", _month(4), 10.0),
        Occurrence("BCP", "RARE", _month(4), 10.0),
    ]

    features = recurrence.recurrence_features(rows)

    assert features[3].months_seen == 1
    assert features[3].rate == pytest.approx(1 / 4)


def test_months_older_than_the_window_do_not_count() -> None:
    rows = [
        Occurrence("BCP", "OLD", _month(0), 10.0),
        Occurrence("BCP", "OLD", _month(20), 10.0),
    ]

    features = recurrence.recurrence_features(rows, window=12)

    assert features[1].months_seen == 0


def test_banks_are_separate_and_digits_collapse_into_one_merchant() -> None:
    rows = [
        Occurrence("BCP", "UBER TRIP 4821", _month(0), 10.0),
        Occurrence("SCOTIABANK", "UBER TRIP 4821", _month(0), 10.0),
        Occurrence("BCP", "UBER TRIP 5530", _month(1), 10.0),
        Occurrence("SCOTIABANK", "OTRO", _month(1), 10.0),
    ]

    features = recurrence.recurrence_features(rows)

    assert features[2].months_seen == 1
    assert features[3].months_seen == 0


def test_two_rows_in_the_same_month_see_the_same_history() -> None:
    rows = [
        *_monthly("GYM", 3),
        Occurrence("BCP", "GYM", _month(2), 80.0),
    ]

    features = recurrence.recurrence_features(rows)

    assert features[2] == features[3]


def test_amount_spread_is_mad_over_median_of_prior_monthly_totals() -> None:
    amounts = [100.0, 110.0, 90.0, 300.0]
    rows = [Occurrence("BCP", "VAR", _month(i), a) for i, a in enumerate(amounts)] + [
        Occurrence("BCP", "VAR", _month(4), 1.0)
    ]

    features = recurrence.recurrence_features(rows)

    assert features[4].amount_spread == pytest.approx(10 / 105)


def test_the_plan_kind_is_looked_up_by_bank_and_merchant() -> None:
    plan = [("BCP", "NETFLIX.COM 123", "fixed"), ("BCP", "RAPPI", "variable")]

    kinds = recurrence.kind_by_merchant(plan)

    assert kinds[recurrence.merchant_key("BCP", "NETFLIX.COM 456")] == "fixed"
    assert recurrence.merchant_key("SCOTIABANK", "RAPPI") not in kinds
