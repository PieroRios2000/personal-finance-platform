"""`forecasting.projection`: the emergency fund, the savings projection and its
scenarios (T60, ADR 0048, spec 4.4 and 4.5). Pure functions over plain inputs; every
number below is synthetic and checked by hand.

The base case is in dollars so the arithmetic is readable: income 3000 a month, fixed
500, variable 1000 (p10 900, p90 1100), so a base saving of 1500. Emergency months 6 on
all spending gives a target of 6 x 1500 = 9000, with 1000 already in the emergency
account, 2000 in other liquid accounts and 5000 in investments. The goal is 10000.
"""

from datetime import date

import pytest
from forecasting.projection import (
    Balances,
    CategoryOutlook,
    EmergencyFund,
    Inputs,
    MonthFlow,
    Plan,
    Projection,
    ProjectionRefused,
    TotalSpend,
    project,
)

LAST_CLOSED = date(2026, 9, 1)
RATE = 4.0


def _plan(**fields: object) -> Plan:
    values: dict[str, object] = {
        "goal_amount": 10000.0,
        "usd_to_pen": RATE,
        "fixed": {"USD": 500.0},
    }
    values.update(fields)
    return Plan(**values)  # type: ignore[arg-type]


def _spend(
    p10: float = 900.0, p50: float = 1000.0, p90: float = 1100.0, scale: float = 1.0
) -> TotalSpend:
    return TotalSpend(
        history=[1000.0 * scale] * 12,
        future=[(p10 * scale, p50 * scale, p90 * scale)] * 3,
    )


def _inputs(**fields: object) -> Inputs:
    values: dict[str, object] = {
        "plan": _plan(),
        "balances": Balances(
            emergency={"USD": 1000.0},
            other_liquid={"USD": 2000.0},
            risk={"USD": 5000.0},
        ),
        "last_closed_month": LAST_CLOSED,
        "income": {"USD": [3000.0] * 12},
        "spend": {"USD": _spend()},
    }
    values.update(fields)
    return Inputs(**values)  # type: ignore[arg-type]


def _months(result: Projection, scenario: str, line: str) -> int | None:
    [row] = [r for r in result.summary if (r.scenario, r.line) == (scenario, line)]
    return row.months_to_goal


def _path(
    result: Projection, scenario: str, line: str
) -> dict[int, tuple[float, float]]:
    return {
        p.month_index: (p.emergency, p.goal_progress)
        for p in result.path
        if (p.scenario, p.line) == (scenario, line)
    }


def _fund(result: Projection, scenario: str = "base") -> EmergencyFund:
    [row] = [r for r in result.emergency if r.scenario == scenario]
    return row


def test_the_emergency_target_is_months_times_fixed_plus_median_variable() -> None:
    fund = _fund(project(_inputs()))

    assert fund.target == pytest.approx(6 * (500 + 1000))
    assert fund.bucket == pytest.approx(1000)
    assert fund.gap == pytest.approx(8000)


def test_fixed_only_counts_just_the_fixed_items() -> None:
    plan = _plan(emergency_basis="fixed_only")

    assert _fund(project(_inputs(plan=plan))).target == pytest.approx(6 * 500)


def test_the_variable_part_is_the_median_of_the_last_six_months() -> None:
    history = [9000.0] * 6 + [1000.0, 1000.0, 1000.0, 2000.0, 2000.0, 9000.0]
    spend = TotalSpend(history=history, future=[(900.0, 1000.0, 1100.0)] * 3)

    fund = _fund(project(_inputs(spend={"USD": spend})))

    assert fund.target == pytest.approx(6 * (500 + 1500))


def test_the_target_does_not_move_with_the_scenario() -> None:
    result = project(_inputs())

    targets = {r.target for r in result.emergency}
    assert len(targets) == 1


def test_base_scenario_times_to_fill_and_to_the_goal() -> None:
    result = project(_inputs())

    assert _fund(result).months_to_fill == 6
    assert _months(result, "base", "liquid") == 11
    assert _months(result, "base", "with_risk") == 8


def test_optimistic_is_never_slower_than_base_and_base_never_slower_than_cautious() -> (
    None
):
    result = project(_inputs())

    for line in ("liquid", "with_risk"):
        optimistic = _months(result, "optimistic", line)
        base = _months(result, "base", line)
        cautious = _months(result, "cautious", line)
        assert optimistic is not None and base is not None and cautious is not None
        assert optimistic <= base <= cautious
    assert _months(result, "optimistic", "liquid") == 10
    assert _months(result, "cautious", "liquid") == 12


def test_the_risk_line_is_never_slower_than_the_liquid_one() -> None:
    result = project(_inputs())

    for scenario in ("base", "cautious", "optimistic"):
        liquid = _path(result, scenario, "liquid")
        risk = _path(result, scenario, "with_risk")
        assert all(risk[i][1] >= liquid[i][1] for i in liquid)
        assert (_months(result, scenario, "with_risk") or 0) <= (
            _months(result, scenario, "liquid") or 10**6
        )


def test_new_savings_fill_the_emergency_account_before_the_goal() -> None:
    path = _path(project(_inputs()), "base", "liquid")

    assert path[0] == (pytest.approx(1000), pytest.approx(2000))
    assert path[5] == (pytest.approx(8500), pytest.approx(2000))
    assert path[6] == (pytest.approx(9000), pytest.approx(3000))
    assert path[7] == (pytest.approx(9000), pytest.approx(4500))


def test_money_above_the_target_in_the_emergency_account_counts_toward_the_goal() -> (
    None
):
    balances = Balances(
        emergency={"USD": 10000.0}, other_liquid={"USD": 2000.0}, risk={"USD": 0.0}
    )

    path = _path(project(_inputs(balances=balances)), "base", "liquid")

    assert path[0] == (pytest.approx(9000), pytest.approx(3000))


def test_beyond_three_months_the_last_forecast_is_held_flat() -> None:
    spend = TotalSpend(
        history=[1000.0] * 12,
        future=[
            (900.0, 1000.0, 1100.0),
            (1100.0, 1200.0, 1300.0),
            (1300.0, 1400.0, 1500.0),
        ],
    )

    path = _path(project(_inputs(spend={"USD": spend})), "base", "liquid")

    steps = [path[i][0] - path[i - 1][0] for i in range(1, 6)]
    assert steps == pytest.approx([1500, 1300, 1100, 1100, 1100])


def test_the_path_runs_120_months_from_the_last_closed_month() -> None:
    result = project(_inputs())

    months = {p.month_index: p.month for p in result.path if p.scenario == "base"}
    assert min(months) == 0 and max(months) == 120
    assert months[0] == LAST_CLOSED
    assert months[1] == date(2026, 10, 1)


def test_no_positive_saving_means_not_reached_never_a_number() -> None:
    spend = _spend(p10=2800.0, p50=3000.0, p90=3200.0)

    result = project(_inputs(spend={"USD": spend}))

    for line in ("liquid", "with_risk"):
        row = [r for r in result.summary if (r.scenario, r.line) == ("base", line)][0]
        assert row.months_to_goal is None and row.reached_month is None
    assert _fund(result).months_to_fill is None


def test_a_goal_too_far_for_120_months_is_not_reached() -> None:
    result = project(_inputs(plan=_plan(goal_amount=10_000_000.0)))

    assert _months(result, "base", "liquid") is None


def test_a_goal_already_covered_is_reached_in_month_zero() -> None:
    balances = Balances(
        emergency={"USD": 9000.0}, other_liquid={"USD": 20000.0}, risk={"USD": 0.0}
    )

    result = project(_inputs(balances=balances))

    assert _months(result, "base", "liquid") == 0
    assert _fund(result).months_to_fill == 0
    assert _fund(result).gap == 0


def test_reached_month_is_the_calendar_month_of_the_answer() -> None:
    [row] = [
        r
        for r in project(_inputs()).summary
        if (r.scenario, r.line) == ("base", "liquid")
    ]

    assert row.reached_month == date(2027, 8, 1)


@pytest.mark.parametrize("rate", [None, 0.0, -3.75])
def test_it_refuses_without_a_positive_rate(rate: float | None) -> None:
    with pytest.raises(ProjectionRefused, match="usd_to_pen"):
        project(_inputs(plan=_plan(usd_to_pen=rate)))


def test_soles_become_dollars_by_dividing_by_the_rate() -> None:
    in_soles = _inputs(
        plan=_plan(fixed={"PEN": 500.0 * RATE}),
        balances=Balances(
            emergency={"PEN": 1000.0 * RATE},
            other_liquid={"PEN": 2000.0 * RATE},
            risk={"PEN": 5000.0 * RATE},
        ),
        income={"PEN": [3000.0 * RATE] * 12},
        spend={"PEN": _spend(scale=RATE)},
    )

    dollars = project(_inputs())
    soles = project(in_soles)

    for scenario in ("base", "cautious", "optimistic"):
        for line in ("liquid", "with_risk"):
            assert _months(soles, scenario, line) == _months(dollars, scenario, line)
    assert _fund(soles).target == pytest.approx(_fund(dollars).target)


def test_the_two_currencies_are_added_after_conversion() -> None:
    mixed = _inputs(
        balances=Balances(
            emergency={"USD": 400.0, "PEN": 600.0 * RATE},
            other_liquid={"USD": 2000.0},
            risk={"USD": 5000.0},
        ),
        income={"USD": [1000.0] * 12, "PEN": [2000.0 * RATE] * 12},
    )

    result = project(mixed)

    assert _fund(result).bucket == pytest.approx(1000)
    assert _months(result, "base", "liquid") == 11


def test_an_income_override_replaces_the_history_and_has_no_spread() -> None:
    plan = _plan(income_override={"USD": 3000.0})
    wavy = {"USD": [1000.0, 5000.0] * 6}

    result = project(_inputs(plan=plan, income=wavy))

    assert _months(result, "base", "liquid") == 11
    summaries = {
        r.scenario: r.projected_monthly_saving
        for r in result.summary
        if r.line == "liquid"
    }
    assert summaries["cautious"] == pytest.approx(3000 - 500 - 1100)
    assert summaries["optimistic"] == pytest.approx(3000 - 500 - 900)


def test_the_scenarios_use_the_income_quartiles_of_the_history() -> None:
    income = {"USD": [2000.0] * 3 + [3000.0] * 6 + [4000.0] * 3}

    result = project(_inputs(income=income))

    savings = {
        r.scenario: r.projected_monthly_saving
        for r in result.summary
        if r.line == "liquid"
    }
    assert savings["base"] == pytest.approx(3000 - 500 - 1000)
    assert savings["cautious"] == pytest.approx(2750 - 500 - 1100)
    assert savings["optimistic"] == pytest.approx(3250 - 500 - 900)


def test_a_missing_interval_makes_the_scenario_use_the_point_forecast() -> None:
    spend = TotalSpend(history=[1000.0] * 12, future=[(None, 1000.0, None)] * 3)

    result = project(_inputs(spend={"USD": spend}))

    assert _months(result, "cautious", "liquid") == _months(result, "base", "liquid")


def test_six_months_of_income_history_is_enough_and_five_is_not() -> None:
    assert project(_inputs(income={"USD": [3000.0] * 6})).summary

    with pytest.raises(ProjectionRefused, match="income"):
        project(_inputs(income={"USD": [3000.0] * 5}))


def test_a_short_income_history_is_fine_with_an_override() -> None:
    plan = _plan(income_override={"USD": 3000.0})

    assert project(_inputs(plan=plan, income={"USD": [3000.0] * 2})).summary


def test_the_required_saving_counts_the_emergency_gap_first() -> None:
    plan = _plan(target_date=date(2027, 9, 1))

    result = project(_inputs(plan=plan))

    liquid = [r for r in result.summary if (r.scenario, r.line) == ("base", "liquid")][
        0
    ]
    risk = [r for r in result.summary if (r.scenario, r.line) == ("base", "with_risk")][
        0
    ]
    assert liquid.required_monthly_saving == pytest.approx((9000 + 8000 - 1000) / 12)
    assert risk.required_monthly_saving == pytest.approx((9000 + 3000 - 1000) / 12)
    assert liquid.projected_monthly_saving == pytest.approx(1500)
    assert liquid.gap == 0


def test_the_gap_is_what_is_missing_to_the_required_saving() -> None:
    plan = _plan(target_date=date(2027, 3, 1))

    [row] = [
        r
        for r in project(_inputs(plan=plan)).summary
        if (r.scenario, r.line) == ("base", "liquid")
    ]

    assert row.required_monthly_saving == pytest.approx((9000 + 8000 - 1000) / 6)
    assert row.gap == pytest.approx(16000 / 6 - 1500)


def test_without_a_target_date_there_is_no_required_saving() -> None:
    [row] = [
        r
        for r in project(_inputs()).summary
        if (r.scenario, r.line) == ("base", "liquid")
    ]

    assert row.required_monthly_saving is None and row.gap is None


def test_headroom_is_the_forecast_above_the_categorys_better_quartile() -> None:
    plan = _plan(target_date=date(2027, 3, 1))
    categories = [
        CategoryOutlook("Comida", "USD", 600.0, [400.0, 500.0, 600.0, 700.0] * 3),
        CategoryOutlook("Taxis", "USD", 100.0, [100.0] * 12),
    ]

    result = project(_inputs(plan=plan, categories=categories))

    food = [h for h in result.headroom if h.category == "Comida"][0]
    taxis = [h for h in result.headroom if h.category == "Taxis"][0]
    assert food.reference == pytest.approx(475)
    assert food.headroom == pytest.approx(125)
    assert taxis.headroom == 0
    assert food.share == pytest.approx(1.0)
    [row] = [r for r in result.summary if (r.scenario, r.line) == ("base", "liquid")]
    assert row.headroom_share_of_gap == pytest.approx(125 / row.gap)  # type: ignore[operator]


def test_headroom_is_converted_to_dollars() -> None:
    categories = [CategoryOutlook("Comida", "PEN", 600.0 * RATE, [400.0 * RATE] * 12)]

    result = project(_inputs(categories=categories))

    assert result.headroom[0].headroom == pytest.approx(200.0)
    assert result.headroom[0].forecast == pytest.approx(600.0)


def _flows(balance_steps: list[float], net: float = 500.0) -> list[MonthFlow]:
    balance, rows = 10000.0, []
    for i, step in enumerate(balance_steps):
        balance += step
        month = date(2026, 3 + i, 1)
        rows.append(
            MonthFlow(
                month,
                income={"USD": 2000.0 + net},
                spending={"USD": 2000.0},
                liquid={"USD": balance},
            )
        )
    return rows


def test_the_cross_check_passes_when_the_balance_follows_the_net_flow() -> None:
    result = project(_inputs(flows=_flows([0.0] + [500.0] * 6)))

    fund = _fund(result)
    assert fund.balance_mismatch is False
    assert fund.months_checked == 6
    assert fund.avg_net_flow == pytest.approx(500)
    assert fund.avg_balance_change == pytest.approx(500)


def test_the_cross_check_warns_when_the_balance_does_not_follow() -> None:
    result = project(_inputs(flows=_flows([0.0] + [-1500.0] * 6)))

    fund = _fund(result)
    assert fund.balance_mismatch is True
    assert fund.mismatch_months == 6
    assert fund.avg_balance_change == pytest.approx(-1500)


def test_a_difference_within_a_quarter_of_spending_is_not_a_mismatch() -> None:
    assert (
        _fund(project(_inputs(flows=_flows([0.0] + [0.0] * 6)))).balance_mismatch
        is False
    )


def test_the_cross_check_is_skipped_with_fewer_than_two_months() -> None:
    fund = _fund(project(_inputs(flows=_flows([0.0]))))

    assert fund.balance_mismatch is None and fund.months_checked == 0


def test_the_income_cross_check_numbers() -> None:
    fund = _fund(project(_inputs()))

    assert fund.months_of_income == pytest.approx(9000 / 3000)
    assert fund.savings_rate == pytest.approx(1500 / 3000)
    assert fund.months_covered == pytest.approx(1000 / 1500)
    assert fund.essential_over_income is False
    assert fund.target_over_two_years_income is False


def test_essential_outflow_above_income_is_flagged() -> None:
    result = project(_inputs(income={"USD": [1200.0] * 12}))

    assert _fund(result).essential_over_income is True


def test_a_target_above_two_years_of_income_is_flagged() -> None:
    plan = _plan(emergency_months=24)

    assert _fund(
        project(_inputs(plan=plan, income={"USD": [1400.0] * 12}))
    ).target_over_two_years_income
