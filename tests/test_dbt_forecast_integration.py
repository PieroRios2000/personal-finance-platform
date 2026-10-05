"""silver.spend_forecast* and the three gold forecast tables (T59, ADR 0048).

Seeds the forecast bronze tables directly through `bronze.replace_forecast_run`, builds
the forecast models and checks the variance verdicts. Deselected by default (needs
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
from tests.test_dbt_gold_integration import lake as _lake
from tests.test_dbt_plan_integration import _seed_spending
from tests.test_dbt_silver_integration import _USER_ID, _dbt_build

pytestmark = pytest.mark.integration

lake = _lake

RUN = date(2026, 9, 1)
SELECT = (
    "spend_forecasts spend_forecast_series fct_spend_forecast "
    "rpt_category_variance rpt_forecast_series_quality rpt_category_forecast "
    "rpt_forecast_realized"
)


def _row(
    category: str, kind: str, target: date, p50: float, **fields: Any
) -> bronze.ForecastRow:
    values: dict[str, Any] = {
        "kind": kind,
        "category": category,
        "currency": "PEN",
        "target_month": target,
        "horizon": 1,
        "model_name": "median_6",
        "p10": p50 - 100,
        "p50": p50,
        "p90": p50 + 100,
        "actual": None,
    }
    values.update(fields)
    return bronze.ForecastRow(**values)


def _month(offset: int) -> date:
    index = RUN.year * 12 + RUN.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def _series(category: str, **fields: Any) -> bronze.ForecastSeriesRow:
    values: dict[str, Any] = {
        "category": category,
        "currency": "PEN",
        "model_name": "median_6",
        "baseline_used": True,
        "low_history": False,
        "n_months": 24,
        "n_origins": 15,
        "mae_rel": 1.0,
        "coverage": 0.8,
    }
    values.update(fields)
    return bronze.ForecastSeriesRow(**values)


def _backtest(category: str, actuals: list[float]) -> list[bronze.ForecastRow]:
    """`actuals` end at the run month; the interval is always 900..1100 around 1000."""
    count = len(actuals)
    return [
        _row(category, "backtest", _month(i - count + 1), 1000.0, actual=actual)
        for i, actual in enumerate(actuals)
    ]


def _rows(relation: str) -> list[dict[str, Any]]:
    with pg_store.connect() as connection:
        cursor = connection.execute(f"select * from {relation} order by 1, 2, 3, 4")
        assert cursor.description is not None
        names = [column.name for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _seed_run() -> None:
    forecasts = (
        _backtest("Above", [1000.0] * 5 + [1500.0])
        + _backtest("Within", [1000.0] * 6)
        + _backtest("Below", [1000.0] * 5 + [500.0])
        + _backtest("Repeat", [1500.0, 1500.0, 1000.0, 1500.0, 1000.0, 1000.0])
        + [_row("Above", "forecast", _month(1), 1000.0)]
        + [
            _row(
                "Sparse",
                "backtest",
                _month(0),
                700.0,
                p10=None,
                p90=None,
                actual=900.0,
            )
        ]
    )
    bronze.replace_forecast_run(
        _USER_ID,
        RUN,
        forecasts,
        [_series(c) for c in ("Above", "Within", "Below", "Repeat")]
        + [_series("Sparse", low_history=True, coverage=None)],
    )


def test_variance_compares_the_last_closed_month_with_its_interval(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()
    _seed_run()

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    rows = {row["category"]: row for row in _rows("gold.rpt_category_variance")}
    assert {c: r["status"] for c, r in rows.items()} == {
        "Above": "above",
        "Within": "within",
        "Below": "below",
        "Repeat": "within",
        "Sparse": "no_interval",
    }
    above = rows["Above"]
    assert above["user_id"] == _USER_ID
    assert above["actual"] == Decimal("1500.00")
    assert above["p90"] == Decimal("1100.00")
    assert above["target_month"] == RUN
    assert above["difference"] == Decimal("500.00")
    assert above["months_above_last_6"] == 1
    assert rows["Repeat"]["months_above_last_6"] == 3
    assert rows["Within"]["months_above_last_6"] == 0


def test_the_forecast_table_keeps_every_run_and_kind(lake: str, tmp_path: Path) -> None:
    _seed_spending()
    _seed_run()
    older = date(2026, 8, 1)
    bronze.replace_forecast_run(
        _USER_ID, older, [_row("Above", "forecast", RUN, 1000.0)], []
    )

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    rows = _rows("gold.fct_spend_forecast")
    assert {r["run_month"] for r in rows} == {RUN, older}
    assert {r["kind"] for r in rows} == {"backtest", "forecast"}
    future = [r for r in rows if r["kind"] == "forecast" and r["run_month"] == RUN]
    assert [r["target_month"] for r in future] == [_month(1)]
    assert future[0]["actual"] is None


def test_series_quality_flags_low_history(lake: str, tmp_path: Path) -> None:
    _seed_spending()
    _seed_run()

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    quality = {r["category"]: r for r in _rows("gold.rpt_forecast_series_quality")}
    assert quality["Sparse"]["low_history"] is True
    assert quality["Sparse"]["coverage"] is None
    assert quality["Above"]["baseline_used"] is True
    assert quality["Above"]["n_origins"] == 15


def test_the_models_build_empty_before_any_forecast_run(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    for table in ("fct_spend_forecast", "rpt_category_variance"):
        assert _rows(f"gold.{table}") == []
    assert _rows("gold.rpt_forecast_series_quality") == []


def test_the_dashboard_forecast_is_the_latest_run_with_its_quality(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()
    _seed_run()
    older = date(2026, 8, 1)
    bronze.replace_forecast_run(
        _USER_ID, older, [_row("Above", "forecast", RUN, 700.0)], [_series("Above")]
    )

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    [row] = _rows("gold.rpt_category_forecast")
    assert (row["user_id"], row["run_month"], row["category"]) == (
        _USER_ID,
        RUN,
        "Above",
    )
    assert row["target_month"] == _month(1)
    assert row["p50"] == Decimal("1000.00")
    assert (row["baseline_used"], row["n_months"]) == (True, 24)


def _realized_rows() -> list[dict[str, Any]]:
    return [r for r in _rows("gold.rpt_forecast_realized") if r["source"] == "realized"]


def test_realized_compares_an_older_forecast_with_the_month_that_then_closed(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()
    older = date(2026, 8, 1)
    bronze.replace_forecast_run(
        _USER_ID,
        older,
        # Backtest misses of 0, 0 and 200 around 1000: the typical miss is 66.67.
        [
            _row("Above", "backtest", date(2026, 6, 1), 1000.0, actual=1000.0),
            _row("Above", "backtest", date(2026, 7, 1), 1000.0, actual=1000.0),
            _row("Above", "backtest", date(2026, 8, 1), 1000.0, actual=1200.0),
            _row("Above", "forecast", RUN, 1000.0),
            _row("Above", "forecast", _month(1), 1000.0, horizon=2),
            _row("Within", "forecast", RUN, 1000.0),
        ],
        [_series("Above"), _series("Within")],
    )
    bronze.replace_forecast_run(
        _USER_ID,
        RUN,
        [
            _row("Above", "backtest", RUN, 1000.0, actual=1500.0),
            _row("Within", "backtest", RUN, 1000.0, actual=1000.0),
        ],
        [_series("Above"), _series("Within")],
    )

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    above, within = _realized_rows()
    assert (above["category"], above["run_month"], above["target_month"]) == (
        "Above",
        older,
        RUN,
    )
    assert (above["actual"], above["p50"]) == (Decimal("1500.00"), Decimal("1000.00"))
    assert above["status"] == "above"
    assert above["realized_error"] == Decimal("500.00")
    assert float(above["backtest_mae"]) == pytest.approx(200 / 3)
    assert float(above["error_ratio"]) == pytest.approx(7.5)
    assert (within["status"], within["realized_error"]) == ("within", Decimal("0.00"))
    assert within["backtest_mae"] is None and within["error_ratio"] is None


def test_nothing_is_realized_while_no_forecast_month_has_closed(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()
    _seed_run()

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _realized_rows() == []


def test_the_dashboard_forecast_says_where_the_interval_stops(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()
    bronze.replace_forecast_run(
        _USER_ID,
        RUN,
        [
            _row("Above", "forecast", _month(1), 1000.0),
            _row(
                "Above", "forecast", _month(24), 1000.0, horizon=24, p10=None, p90=None
            ),
        ],
        [_series("Above")],
    )

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    rows = {r["horizon"]: r for r in _rows("gold.rpt_category_forecast")}
    assert rows[1]["has_interval"] is True
    assert rows[24]["has_interval"] is False and rows[24]["p10"] is None
    flags = {
        r["horizon"]: r["has_interval"]
        for r in _rows("gold.fct_spend_forecast")
        if r["kind"] == "forecast"
    }
    assert flags == {1: True, 24: False}


def test_realized_shows_the_backtest_until_a_forecast_month_has_closed(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()
    _seed_run()

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    rows = _rows("gold.rpt_forecast_realized")
    assert rows
    assert {r["source"] for r in rows} == {"backtest"}
    above = [r for r in rows if r["category"] == "Above"]
    assert all(r["actual"] is not None and r["horizon"] == 1 for r in above)
    assert {r["status"] for r in above} <= {"above", "below", "within", "no_interval"}


def test_realized_labels_each_row_by_where_its_actual_comes_from(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()
    older = date(2026, 8, 1)
    bronze.replace_forecast_run(
        _USER_ID,
        older,
        [
            _row("Above", "backtest", date(2026, 8, 1), 1000.0, actual=1200.0),
            _row("Above", "forecast", RUN, 1000.0),
        ],
        [_series("Above")],
    )
    bronze.replace_forecast_run(
        _USER_ID,
        RUN,
        [_row("Above", "backtest", RUN, 1000.0, actual=1500.0)],
        [_series("Above")],
    )

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    by_source: dict[str, list[date]] = {}
    for row in _rows("gold.rpt_forecast_realized"):
        by_source.setdefault(row["source"], []).append(row["target_month"])
    assert by_source["realized"] == [RUN]
    assert sorted(by_source["backtest"]) == [date(2026, 8, 1), RUN]
