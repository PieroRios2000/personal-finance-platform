"""The dynamic goal (T65, ADR 0048): the Superset virtual dataset
`bi/sql/goal_dynamic.sql` gives the same answer as `forecasting.projection` for the same
inputs, whatever goal, exchange rate and emergency months the dashboard filters set.

Seeds the bronze tables from the real projection (`scripts.goal_projection._tables`),
builds the gold models and runs the rendered SQL. Deselected by default (needs
SeaweedFS and Postgres, like the rest of the dbt integration suite). Run with
`pytest -m integration`. All data is synthetic.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from forecasting.projection import (
    Balances,
    Inputs,
    Plan,
    Projection,
    TotalSpend,
    project,
)
from lakehouse import bronze
from scripts.goal_projection import _tables
from tests import pg_store
from tests.goal_dynamic_sql import render
from tests.test_dbt_gold_integration import lake as _lake
from tests.test_dbt_silver_integration import _USER_ID, _dbt_build

pytestmark = pytest.mark.integration

lake = _lake

RUN = date(2026, 9, 1)
SELECT = (
    "plan_goal goal_cashflow goal_balances emergency_fund "
    "rpt_goal_plan rpt_goal_cashflow rpt_goal_balances rpt_emergency_fund"
)
PLAN = Plan(
    goal_amount=30000.0,
    usd_to_pen=4.0,
    emergency_months=6,
    target_date=date(2028, 3, 1),
    fixed={"PEN": 800.0, "USD": 100.0},
)
SCENARIO_STEP = {"base": 0, "cautious": 1, "optimistic": 2}


def _inputs(plan: Plan = PLAN) -> Inputs:
    pen_future: list[tuple[float | None, float, float | None]] = [
        (900.0 + 10 * i, 1000.0 + 10 * i, 1100.0 + 10 * i) for i in range(12)
    ] + [(None, 1200.0 + 5 * i, None) for i in range(24)]
    usd_future: list[tuple[float | None, float, float | None]] = [
        (120.0, 150.0, 190.0)
    ] * 12 + [(None, 160.0, None)] * 24
    pen = TotalSpend([1000.0 + 20 * (i % 4) for i in range(12)], pen_future)
    usd = TotalSpend([150.0] * 12, usd_future)
    return Inputs(
        plan=plan,
        balances=Balances(
            emergency={"PEN": 4000.0},
            other_liquid={"PEN": 6000.0, "USD": 500.0},
            risk={"USD": 3000.0},
        ),
        last_closed_month=RUN,
        income={"PEN": [4000.0] * 12, "USD": [300.0] * 12},
        spend={"PEN": pen, "USD": usd},
    )


def _seed(plan: Plan = PLAN, user: str = _USER_ID) -> Projection:
    projection = project(_inputs(plan))
    bronze.replace_plan(
        user,
        [],
        bronze.PlanGoalRow(
            goal_amount=plan.goal_amount,
            usd_to_pen=plan.usd_to_pen or 0.0,
            emergency_months=plan.emergency_months,
            emergency_basis=plan.emergency_basis,
            emergency_account="Ripley",
            target_date=plan.target_date,
            income_pen_override=None,
            income_usd_override=None,
        ),
    )
    bronze.replace_goal_projection(user, RUN, _tables(projection))
    return projection


def _rows(sql: str) -> list[dict[str, Any]]:
    with pg_store.connect() as connection:
        cursor = connection.execute(sql)
        assert cursor.description is not None
        names = [column.name for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _build(tmp_path: Path) -> None:
    result = _dbt_build(tmp_path, select=SELECT)
    assert result.returncode == 0, result.stdout + result.stderr


def _sql(filters: Mapping[str, Sequence[object]] | None = None) -> list[dict[str, Any]]:
    return _rows(render(filters))


def _compare(rows: list[dict[str, Any]], expected: Projection) -> None:
    path = {(r["scenario"], r["line"], r["month_index"]): r for r in rows}
    assert len(path) == len(rows) == len(expected.path)
    for point in expected.path:
        row = path[(point.scenario, point.line, point.month_index)]
        assert row["month"] == point.month
        assert float(row["emergency"]) == pytest.approx(point.emergency, abs=0.5)
        assert float(row["goal_progress"]) == pytest.approx(
            point.goal_progress, abs=0.5
        )
    for summary in expected.summary:
        row = path[(summary.scenario, summary.line, 0)]
        assert row["months_to_goal"] == summary.months_to_goal
        assert row["reached_month"] == summary.reached_month
        assert float(row["projected_monthly_saving"]) == pytest.approx(
            summary.projected_monthly_saving, abs=0.05
        )
        if summary.required_monthly_saving is None:
            assert row["required_monthly_saving"] is None
        else:
            assert float(row["required_monthly_saving"]) == pytest.approx(
                summary.required_monthly_saving, abs=0.05
            )
    for fund in expected.emergency:
        row = path[(fund.scenario, "liquid", 0)]
        assert float(row["emergency_target"]) == pytest.approx(fund.target, abs=0.05)
        assert float(row["emergency_now"]) == pytest.approx(fund.bucket, abs=0.05)
        assert float(row["emergency_gap"]) == pytest.approx(fund.gap, abs=0.05)
        assert row["months_to_fill"] == fund.months_to_fill
        assert float(row["months_covered"]) == pytest.approx(
            fund.months_covered or 0.0, abs=0.01
        )
        assert float(row["months_of_income"]) == pytest.approx(
            fund.months_of_income or 0.0, abs=0.01
        )
        assert row["essential_over_income"] is fund.essential_over_income
        assert row["target_over_two_years_income"] is fund.target_over_two_years_income


def test_the_sql_gives_the_python_answer_with_the_plans_own_numbers(
    lake: str, tmp_path: Path
) -> None:
    expected = _seed()
    _build(tmp_path)

    rows = _sql()

    _compare(rows, expected)
    assert {r["user_id"] for r in rows} == {_USER_ID}
    assert {
        (r["goal_amount_usd"], r["usd_to_pen"], r["emergency_months"]) for r in rows
    } == {(30000, 4, 6)}
    assert {r["horizon_months"] for r in rows} == {36}


@pytest.mark.parametrize(
    ("typed", "changes"),
    [
        ({"goal_amount_usd": ["12000"]}, {"goal_amount": 12000.0}),
        ({"usd_to_pen": ["3.5"]}, {"usd_to_pen": 3.5}),
        ({"emergency_months": ["3"]}, {"emergency_months": 3}),
        (
            {
                "goal_amount_usd": ["50,000"],
                "usd_to_pen": ["5"],
                "emergency_months": ["0"],
            },
            {"goal_amount": 50000.0, "usd_to_pen": 5.0, "emergency_months": 0},
        ),
    ],
)
def test_the_sql_follows_the_filters_like_a_python_run_with_the_same_plan(
    lake: str, tmp_path: Path, typed: dict[str, list[object]], changes: dict[str, Any]
) -> None:
    _seed()
    _build(tmp_path)

    _compare(_sql(typed), project(_inputs(replace(PLAN, **changes))))


def test_typing_a_goal_and_a_rate_changes_the_answer(lake: str, tmp_path: Path) -> None:
    _seed()
    _build(tmp_path)

    def months(filters: dict[str, list[object]]) -> int | None:
        [row] = [
            r
            for r in _sql(filters)
            if (r["scenario"], r["line"], r["month_index"]) == ("base", "liquid", 0)
        ]
        months_to_goal: int | None = row["months_to_goal"]
        return months_to_goal

    assert months({"goal_amount_usd": ["12000"]}) != months(
        {"goal_amount_usd": ["90000"]}
    )
    assert months({"usd_to_pen": ["3"]}) != months({"usd_to_pen": ["6"]})


def test_a_hostile_filter_value_changes_nothing(lake: str, tmp_path: Path) -> None:
    _seed()
    _build(tmp_path)

    hostile = {"goal_amount_usd": ["1; drop table gold.rpt_goal_plan; --"]}

    assert _sql(hostile) == _sql()
    assert _rows("select count(*) as n from gold.rpt_goal_plan")[0]["n"] == 1


def test_every_user_gets_the_answer_of_their_own_plan(
    lake: str, tmp_path: Path
) -> None:
    mine = _seed()
    other_plan = replace(PLAN, goal_amount=12000.0)
    theirs = _seed(other_plan, user="someone-else")
    _build(tmp_path)

    rows = _sql()

    _compare([r for r in rows if r["user_id"] == _USER_ID], mine)
    _compare([r for r in rows if r["user_id"] == "someone-else"], theirs)
