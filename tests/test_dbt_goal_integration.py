"""silver and gold goal-projection tables (T60, ADR 0048).

Seeds the four bronze tables through `bronze.replace_goal_projection`, builds the models
on them and checks what the dashboard reads. Deselected by default (needs SeaweedFS and
Postgres, like the rest of the dbt integration suite). Run with `pytest -m integration`.
All data is synthetic.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from lakehouse import bronze
from tests import pg_store
from tests.test_dbt_gold_integration import lake as _lake
from tests.test_dbt_silver_integration import _USER_ID, _dbt_build

pytestmark = pytest.mark.integration

lake = _lake

RUN = date(2026, 9, 1)
SELECT = (
    "goal_projection goal_summary emergency_fund goal_headroom "
    "rpt_goal_projection rpt_goal_summary rpt_emergency_fund rpt_goal_headroom"
)
GOLD = ("rpt_goal_projection", "rpt_goal_summary", "rpt_emergency_fund")


def _rows(relation: str) -> list[dict[str, Any]]:
    with pg_store.connect() as connection:
        cursor = connection.execute(f"select * from {relation} order by 1, 2, 3, 4")
        assert cursor.description is not None
        names = [column.name for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _seed() -> None:
    fund = {
        "target": 9000.0,
        "bucket": 1000.0,
        "gap": 8000.0,
        "months_to_fill": 6,
        "months_covered": 0.5,
        "months_of_income": 3.0,
        "savings_rate": 0.2,
        "essential_over_income": False,
        "target_over_two_years_income": False,
        "balance_mismatch": None,
        "mismatch_months": 0,
        "months_checked": 0,
        "avg_net_flow": None,
        "avg_balance_change": None,
    }
    summary = {
        "months_to_goal": None,
        "reached_month": None,
        "required_monthly_saving": 1333.33,
        "projected_monthly_saving": 1500.0,
        "gap": 0.0,
        "headroom_share_of_gap": None,
    }
    bronze.replace_goal_projection(
        _USER_ID,
        RUN,
        {
            "goal_projection": [
                {
                    "scenario": scenario,
                    "line": line,
                    "month_index": index,
                    "month": date(2026, 9 + index, 1),
                    "emergency": 1000.0 + 500 * index,
                    "goal_progress": 2000.0,
                }
                for scenario in ("base", "cautious")
                for line in ("liquid", "with_risk")
                for index in (0, 1)
            ],
            "goal_summary": [
                {"scenario": "base", "line": "liquid", **summary},
                {
                    "scenario": "base",
                    "line": "with_risk",
                    **summary,
                    "months_to_goal": 8,
                    "reached_month": date(2027, 5, 1),
                },
            ],
            "emergency_fund": [
                {"scenario": "base", **fund},
                {"scenario": "cautious", **fund, "balance_mismatch": True},
            ],
            "goal_headroom": [
                {
                    "category": "Alimentacion",
                    "currency": "PEN",
                    "forecast": 300.0,
                    "reference": 250.0,
                    "headroom": 50.0,
                    "share": 1.0,
                }
            ],
        },
    )


def test_the_projection_reaches_gold_with_its_user_and_run(
    lake: str, tmp_path: Path
) -> None:
    _seed()

    result = _dbt_build(tmp_path, select=SELECT)

    assert result.returncode == 0, result.stdout + result.stderr
    path = _rows("gold.rpt_goal_projection")
    assert len(path) == 8
    assert {(r["user_id"], r["run_month"]) for r in path} == {(_USER_ID, RUN)}
    assert path[1]["emergency"] == Decimal("1500.00")
    summary = {r["line"]: r for r in _rows("gold.rpt_goal_summary")}
    assert summary["liquid"]["months_to_goal"] is None
    assert summary["with_risk"]["reached_month"] == date(2027, 5, 1)
    fund = {r["scenario"]: r for r in _rows("gold.rpt_emergency_fund")}
    assert fund["base"]["target"] == Decimal("9000.00")
    assert fund["base"]["balance_mismatch"] is None
    assert fund["cautious"]["balance_mismatch"] is True
    assert _rows("gold.rpt_goal_headroom")[0]["headroom"] == Decimal("50.00")


def test_the_tables_are_empty_before_any_projection(lake: str, tmp_path: Path) -> None:
    result = _dbt_build(tmp_path, select=SELECT)

    assert result.returncode == 0, result.stdout + result.stderr
    for relation in GOLD:
        assert _rows(f"gold.{relation}") == []


def test_a_refused_projection_leaves_no_stale_answer(lake: str, tmp_path: Path) -> None:
    _seed()
    bronze.replace_goal_projection(_USER_ID, RUN, {})

    result = _dbt_build(tmp_path, select=SELECT)

    assert result.returncode == 0, result.stdout + result.stderr
    for relation in (*GOLD, "rpt_goal_headroom"):
        assert _rows(f"gold.{relation}") == []
