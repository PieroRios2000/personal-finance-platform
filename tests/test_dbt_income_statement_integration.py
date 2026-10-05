"""gold.rpt_income_statement: the monthly income statement (T66, ADR 0048).

Seeds statements, labels, the plan, one forecast run and the goal projection's cash flow
directly, builds dbt and checks the lines of each month. Deselected by default (needs
SeaweedFS and Postgres, like the rest of the dbt integration suite). Run with
`pytest -m integration`. All data is synthetic.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from lakehouse import bronze
from tests import pg_store
from tests.test_dbt_gold_integration import _month_bounds
from tests.test_dbt_gold_integration import lake as _lake
from tests.test_dbt_plan_integration import _goal, _item, _statement_for
from tests.test_dbt_silver_integration import _BANK, _USER_ID, _dbt_build

pytestmark = pytest.mark.integration

lake = _lake

RUN = _month_bounds(1)[0]
BASE = "3000"


def _month(offset: int) -> date:
    """The first day of the month `offset` months after the last closed one."""
    index = RUN.year * 12 + RUN.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def _seed_months() -> None:
    """Three closed months (salary, a fixed rent, a streaming service, and food in the
    last one) and a big rent charge in the open month that must not be counted."""
    base = {
        "planted salary": f"-{BASE}",
        "planted rent": "1000",
        "planted stream": "30",
    }
    charges = {
        3: base,
        2: base,
        1: {**base, "planted food": "400"},
        0: {"planted rent": "5000"},
    }
    balance = Decimal("50000")
    for months_ago in range(3, -1, -1):
        balance = _statement_for(months_ago, charges[months_ago], balance)
    bronze.replace_category_labels(
        _USER_ID,
        [
            (_BANK, "PLANTED STREAM", "Entretenimiento", True),
            (_BANK, "PLANTED FOOD", "Alimentación", True),
        ],
    )


def _plan() -> None:
    bronze.replace_plan(
        _USER_ID,
        [
            _item("PLANTED RENT", "fixed", 1000.0),
            _item("PLANTED STREAM", "variable", 30.0),
            _item("PLANTED FOOD", "variable", 300.0),
        ],
        _goal(),
    )


def _forecast_row(
    kind: str, category: str, target: date, horizon: int, p50: float, **fields: Any
) -> bronze.ForecastRow:
    values: dict[str, Any] = {
        "kind": kind,
        "category": category,
        "currency": "PEN",
        "target_month": target,
        "horizon": horizon,
        "model_name": "median_6",
        "p10": p50 - 10,
        "p50": p50,
        "p90": p50 + 10,
        "actual": None,
    }
    values.update(fields)
    return bronze.ForecastRow(**values)


def _seed_forecast() -> None:
    rows = [
        _forecast_row("backtest", "Total", _month(offset), 1, 100.0, actual=100.0)
        for offset in (-2, -1, 0)
    ] + [
        _forecast_row("forecast", "Total", _month(1), 1, 150.0),
        _forecast_row("forecast", "Total", _month(2), 2, 160.0),
        _forecast_row("forecast", "Alimentación", _month(1), 1, 120.0),
        _forecast_row("forecast", "Alimentación", _month(2), 2, 130.0),
        _forecast_row("forecast", "Entretenimiento", _month(1), 1, 20.0),
        _forecast_row("forecast", "Entretenimiento", _month(2), 2, 30.0),
    ]
    bronze.replace_forecast_run(_USER_ID, RUN, rows, [])
    bronze.replace_goal_projection(
        _USER_ID,
        RUN,
        {
            "goal_cashflow": [
                {
                    "scenario": scenario,
                    "month_index": index,
                    "month": _month(index),
                    "currency": "PEN",
                    "income": income + 100 * (index - 1),
                    "fixed": 1000.0,
                    "variable": 150.0 + 10 * (index - 1),
                }
                for scenario, income in (("base", 3000.0), ("cautious", 2000.0))
                for index in (1, 2)
            ]
        },
    )


def _lines(month: date, currency: str = "PEN") -> dict[str, tuple[Decimal, str]]:
    with pg_store.connect() as connection:
        rows = connection.execute(
            "select line, amount, kind from gold.rpt_income_statement "
            "where month = ? and currency = ?",
            (month, currency),
        ).fetchall()
    return {line: (Decimal(amount), kind) for line, amount, kind in rows}


def _amounts(month: date) -> dict[str, Decimal]:
    return {line: amount for line, (amount, _) in _lines(month).items()}


def _build(tmp_path: Path) -> None:
    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_closed_month_shows_what_happened_and_what_was_planned(
    lake: str, tmp_path: Path
) -> None:
    _seed_months()
    _plan()
    _seed_forecast()

    _build(tmp_path)

    assert _amounts(_month(0)) == {
        "1 · Income": Decimal("3000"),
        "2 · Fixed expenses": Decimal("1000"),
        "3 · Alimentación": Decimal("400"),
        "3 · Entretenimiento": Decimal("30"),
        "4 · Total expenses": Decimal("1430"),
        "5 · Monthly saving": Decimal("1570"),
        "6 · Expected expenses": Decimal("1100"),
        "7 · Planned saving": Decimal("1900"),
        "8 · Saving vs plan": Decimal("-330"),
    }
    earlier = _lines(_month(-2))
    assert earlier["5 · Monthly saving"] == (Decimal("1970"), "actual")
    assert earlier["7 · Planned saving"] == (Decimal("1900"), "plan")
    assert earlier["8 · Saving vs plan"][0] == Decimal("70")


def test_the_months_ahead_come_from_the_forecast_and_the_base_scenario(
    lake: str, tmp_path: Path
) -> None:
    _seed_months()
    _plan()
    _seed_forecast()

    _build(tmp_path)

    assert _lines(_month(1)) == {
        "1 · Income": (Decimal("3000"), "forecast"),
        "2 · Fixed expenses": (Decimal("1000"), "forecast"),
        "3 · Alimentación": (Decimal("120"), "forecast"),
        "3 · Entretenimiento": (Decimal("20"), "forecast"),
        "3 · ~ Not split by category": (Decimal("10"), "forecast"),
        "4 · Total expenses": (Decimal("1150"), "forecast"),
        "5 · Monthly saving": (Decimal("1850"), "forecast"),
        "6 · Expected expenses": (Decimal("1150"), "plan"),
        "7 · Planned saving": (Decimal("1850"), "plan"),
    }
    assert _amounts(_month(2))["5 · Monthly saving"] == Decimal("1940")


def test_the_open_month_is_never_counted_as_an_actual(
    lake: str, tmp_path: Path
) -> None:
    _seed_months()
    _plan()
    _seed_forecast()

    _build(tmp_path)

    with pg_store.connect() as connection:
        [(count,)] = connection.execute(
            "select count(*) from gold.rpt_income_statement "
            "where kind = 'actual' and month >= date_trunc('month', current_date)"
        ).fetchall()
        labels = connection.execute(
            "select distinct month_label from gold.rpt_income_statement "
            "where month = ?",
            (_month(1),),
        ).fetchall()
    assert count == 0
    assert labels == [(f"{_month(1):%Y-%m} (forecast)",)]
    assert all(user == _USER_ID for user in _users())


def _users() -> list[str]:
    with pg_store.connect() as connection:
        rows = connection.execute(
            "select distinct user_id from gold.rpt_income_statement"
        ).fetchall()
    return [user for (user,) in rows]


def test_without_a_plan_or_a_forecast_it_is_just_what_happened(
    lake: str, tmp_path: Path
) -> None:
    _seed_months()

    _build(tmp_path)

    assert _amounts(_month(0)) == {
        "1 · Income": Decimal("3000"),
        "3 · Alimentación": Decimal("400"),
        "3 · Entretenimiento": Decimal("30"),
        "3 · Sin categorizar": Decimal("1000"),
        "4 · Total expenses": Decimal("1430"),
        "5 · Monthly saving": Decimal("1570"),
    }
