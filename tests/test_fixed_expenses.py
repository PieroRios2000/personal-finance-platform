"""`forecasting.fixed_expenses`: which recurring charges look fixed. Every series is
synthetic and planted, so a test fails when the rule changes, not when a real statement
does (T56, ADR 0048)."""

from datetime import date

import pytest
from forecasting.fixed_expenses import Candidate, MonthlySpend, detect_candidates

LAST = date(2026, 9, 1)


def _month(back: int) -> date:
    """First day of the month `back` months before LAST."""
    index = LAST.year * 12 + LAST.month - 1 - back
    return date(index // 12, index % 12 + 1, 1)


def _series(
    description: str,
    amounts: list[float | None],
    *,
    bank: str = "BCP",
    currency: str = "PEN",
    category: str = "Servicios",
) -> list[MonthlySpend]:
    """`amounts[0]` is the oldest month of a window ending at LAST; None = no charge."""
    count = len(amounts)
    return [
        MonthlySpend(bank, description, currency, category, _month(count - 1 - i), a)
        for i, a in enumerate(amounts)
        if a is not None
    ]


def _by_description(candidates: list[Candidate]) -> dict[str, Candidate]:
    return {c.description: c for c in candidates}


def test_a_charge_with_the_same_amount_every_month_is_proposed_fixed() -> None:
    found = _by_description(detect_candidates(_series("PLANTED RENT", [1200.0] * 6)))

    assert found["PLANTED RENT"].proposed_kind == "fixed"
    assert found["PLANTED RENT"].months_seen == 6
    assert found["PLANTED RENT"].typical_amount == 1200.0


def test_a_small_amount_drift_is_still_fixed() -> None:
    amounts: list[float | None] = [100.0, 104.0, 98.0, 101.0, 99.0, 103.0]

    found = _by_description(detect_candidates(_series("PLANTED PHONE", amounts)))

    assert found["PLANTED PHONE"].proposed_kind == "fixed"
    assert found["PLANTED PHONE"].typical_amount == 100.5


def test_a_recurring_charge_with_a_large_spread_is_listed_but_variable() -> None:
    amounts: list[float | None] = [80.0, 210.0, 130.0, 55.0, 190.0, 95.0]

    found = _by_description(detect_candidates(_series("PLANTED SUPERMARKET", amounts)))

    assert found["PLANTED SUPERMARKET"].proposed_kind == "variable"


def test_four_of_the_last_six_months_is_enough_and_three_is_not() -> None:
    four: list[float | None] = [50.0, None, 50.0, 50.0, None, 50.0]
    three: list[float | None] = [50.0, None, None, 50.0, None, 50.0]
    rows = _series("PLANTED FOUR", four) + _series("PLANTED THREE", three)

    found = _by_description(detect_candidates(rows))

    assert found["PLANTED FOUR"].months_seen == 4
    assert "PLANTED THREE" not in found


def test_a_one_off_charge_is_not_listed() -> None:
    rows = _series("PLANTED ONE OFF", [None, None, None, None, None, 900.0])

    assert detect_candidates(rows) == []


def test_only_the_last_six_months_of_the_data_count() -> None:
    # Seen every month a year ago, never in the last six: not a candidate now.
    old = [
        MonthlySpend("BCP", "PLANTED OLD", "PEN", "Servicios", _month(back), 70.0)
        for back in range(6, 12)
    ]

    found = _by_description(detect_candidates(old + _series("PLANTED NOW", [10.0] * 6)))

    assert "PLANTED NOW" in found
    assert "PLANTED OLD" not in found


def test_the_window_ends_at_the_latest_month_with_data() -> None:
    # Data stops in July: July is the end of the window, not the calendar's today.
    rows = [
        MonthlySpend("BCP", "PLANTED STOPPED", "PEN", "Servicios", _month(back), 40.0)
        for back in range(2, 8)
    ]

    found = _by_description(detect_candidates(rows))

    assert found["PLANTED STOPPED"].months_seen == 6


def test_charges_in_the_same_month_are_added_before_judging_the_amount() -> None:
    rows = [
        MonthlySpend("BCP", "PLANTED SPLIT", "PEN", "Servicios", _month(back), amount)
        for back in range(6)
        for amount in (30.0, 20.0)
    ]

    found = _by_description(detect_candidates(rows))

    assert found["PLANTED SPLIT"].typical_amount == 50.0
    assert found["PLANTED SPLIT"].proposed_kind == "fixed"


def test_the_same_description_in_two_currencies_is_two_candidates_with_a_note() -> None:
    rows = _series("PLANTED CLOUD", [10.0] * 6, currency="USD") + _series(
        "PLANTED CLOUD", [38.0] * 6, currency="PEN"
    )

    found = detect_candidates(rows)

    assert sorted(c.currency for c in found) == ["PEN", "USD"]
    assert all("USD" in c.note or "PEN" in c.note for c in found)
    pen = next(c for c in found if c.currency == "PEN")
    assert "USD" in pen.note


def test_two_banks_with_the_same_description_stay_separate() -> None:
    rows = _series("PLANTED SAME", [20.0] * 6, bank="BCP") + _series(
        "PLANTED SAME", [20.0] * 6, bank="Scotiabank"
    )

    assert sorted(c.bank for c in detect_candidates(rows)) == ["BCP", "Scotiabank"]


def test_only_the_planted_fixed_items_are_proposed_fixed() -> None:
    rows = (
        _series("PLANTED RENT", [1200.0] * 6)
        + _series("PLANTED GYM", [90.0, 90.0, 90.0, 90.0, 90.0, None])
        + _series("PLANTED SUPERMARKET", [80.0, 210.0, 130.0, 55.0, 190.0, 95.0])
        + _series("PLANTED ONE OFF", [None, None, None, None, None, 900.0])
    )

    candidates = detect_candidates(rows)

    fixed = {c.description for c in candidates if c.proposed_kind == "fixed"}
    assert fixed == {"PLANTED RENT", "PLANTED GYM"}
    assert {c.description for c in candidates} == {
        "PLANTED RENT",
        "PLANTED GYM",
        "PLANTED SUPERMARKET",
    }


def test_the_result_is_ordered_and_deterministic() -> None:
    rows = _series("PLANTED B", [20.0] * 6) + _series("PLANTED A", [20.0] * 6)

    first = detect_candidates(rows)

    assert first == detect_candidates(list(reversed(rows)))
    assert [c.description for c in first] == ["PLANTED A", "PLANTED B"]


def test_no_rows_gives_no_candidates() -> None:
    assert detect_candidates([]) == []


@pytest.mark.parametrize("amount", [0.0, -5.0])
def test_a_non_positive_total_is_not_a_charge(amount: float) -> None:
    assert detect_candidates(_series("PLANTED REFUND", [amount] * 6)) == []
