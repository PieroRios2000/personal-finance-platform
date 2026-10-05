"""`scripts/forecast.py`: forecasts every series of the closed months, hands the rows
to `lakehouse.bronze.replace_forecast_run` and logs ratios and counts to MLflow (T59,
ADR 0048, spec 4.6). The Delta write is `tests/test_bronze.py`'s job; the models that
read it are `tests/test_dbt_forecast_integration.py`'s. All names and amounts here
are synthetic."""

from datetime import date
from typing import Any, NamedTuple

import mlflow
import numpy as np
import pytest

from forecasting.fixed_expenses import MonthlySpend
from lakehouse import bronze
from scripts import forecast as fc
from scripts import goal_projection as gp

TODAY = date(2026, 10, 4)
CATEGORY = "PLANTEDCATEGORY"
SHOP = "PLANTEDSHOP"


class Written(NamedTuple):
    user_id: str
    run_month: date
    forecasts: list[bronze.ForecastRow]
    series: list[bronze.ForecastSeriesRow]


def _months(count: int, end: date = date(2026, 9, 1)) -> list[date]:
    last = end.year * 12 + end.month - 1
    return [date((last - i) // 12, (last - i) % 12 + 1, 1) for i in range(count)][::-1]


def _spend(
    category: str = CATEGORY,
    description: str = SHOP,
    currency: str = "PEN",
    count: int = 24,
    seed: int = 0,
) -> list[MonthlySpend]:
    noise = np.random.default_rng(seed).normal(0, 80, count)
    return [
        MonthlySpend("BCP", description, currency, category, month, 1000.0 + float(e))
        for month, e in zip(_months(count), noise, strict=True)
    ]


projected: list[tuple[Any, ...]] = []


@pytest.fixture
def written(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> list[Written]:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}")
    calls: list[Written] = []
    projected.clear()

    def capture(
        user_id: str,
        run_month: date,
        forecasts: list[bronze.ForecastRow],
        series: list[bronze.ForecastSeriesRow],
    ) -> None:
        calls.append(Written(user_id, run_month, forecasts, series))

    monkeypatch.setattr(bronze, "replace_forecast_run", capture)
    monkeypatch.setattr(fc, "fetch_plan_exclusions", lambda user_id: set())
    monkeypatch.setattr(fc, "fetch_monthly_spend", lambda user_id: _spend())
    monkeypatch.setattr(gp, "run", lambda *args: projected.append(args))
    return calls


def test_the_run_month_is_the_last_closed_month(written: list[Written]) -> None:
    assert fc.run("piero", TODAY) == 0

    [call] = written
    assert call.user_id == "piero"
    assert call.run_month == date(2026, 9, 1)


def test_future_rows_look_three_months_past_the_last_closed_month(
    written: list[Written],
) -> None:
    fc.run("piero", TODAY)

    future = [r for r in written[0].forecasts if r.kind == "forecast"]
    mine = sorted(r for r in future if r.category == CATEGORY)
    assert [(r.horizon, r.target_month) for r in mine] == [
        (1, date(2026, 10, 1)),
        (2, date(2026, 11, 1)),
        (3, date(2026, 12, 1)),
    ]
    assert all(r.actual is None for r in future)


def test_backtest_rows_carry_the_actual_of_each_month(written: list[Written]) -> None:
    fc.run("piero", TODAY)

    past = [r for r in written[0].forecasts if r.kind == "backtest"]
    mine = [r for r in past if r.category == CATEGORY]
    assert len(mine) == 24 - 9
    assert max(r.target_month for r in mine) == date(2026, 9, 1)
    assert all(r.horizon == 1 and r.actual is not None for r in mine)


def test_every_category_gets_a_total_and_a_series_row(written: list[Written]) -> None:
    fc.run("piero", TODAY)

    names = {(r.category, r.currency) for r in written[0].series}
    assert names == {(CATEGORY, "PEN"), ("Total", "PEN")}


def test_fixed_and_ignored_items_leave_the_series(
    written: list[Written], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        fc,
        "fetch_monthly_spend",
        lambda user_id: _spend() + _spend("Servicios", "PLANTEDRENT", seed=1),
    )
    monkeypatch.setattr(
        fc, "fetch_plan_exclusions", lambda user_id: {("BCP", "PLANTEDRENT", "PEN")}
    )

    fc.run("piero", TODAY)

    assert {r.category for r in written[0].series} == {CATEGORY, "Total"}


def test_the_goal_is_projected_from_the_same_fits_after_the_forecast_is_written(
    written: list[Written],
) -> None:
    fc.run("piero", TODAY)

    [(user_id, run_month, fits, series, spending)] = projected
    assert (user_id, run_month) == ("piero", date(2026, 9, 1))
    assert len(fits) == len(series) == 2
    assert len(spending) == 24


def test_a_run_that_writes_nothing_does_not_project(
    written: list[Written], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fc, "fetch_monthly_spend", lambda user_id: [])

    fc.run("piero", TODAY)

    assert projected == []


def test_two_runs_produce_the_same_rows(written: list[Written]) -> None:
    fc.run("piero", TODAY)
    fc.run("piero", TODAY)

    assert written[0] == written[1]


def test_a_run_without_a_plan_still_forecasts_and_says_so(
    written: list[Written], monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(fc, "fetch_plan_exclusions", lambda user_id: None)

    assert fc.run("piero", TODAY) == 0

    assert "no plan imported" in capsys.readouterr().out
    assert written[0].series


def test_no_spending_is_an_error_and_writes_nothing(
    written: list[Written], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fc, "fetch_monthly_spend", lambda user_id: [])

    assert fc.run("piero", TODAY) == 1
    assert written == []


def test_main_requires_a_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    assert fc.main([]) == 2


def test_the_console_shows_counts_only(written: list[Written], capsys: Any) -> None:
    fc.run("piero", TODAY)

    out = capsys.readouterr().out
    assert CATEGORY not in out and SHOP not in out
    assert "2 series" in out


def _logged_text() -> str:
    experiment = mlflow.get_experiment_by_name("spend-forecast")
    assert experiment is not None
    runs = mlflow.search_runs([experiment.experiment_id], output_format="list")
    assert len(runs) == 1
    run = runs[0]
    parts = [experiment.name, str(run.info.run_name)]
    parts += [f"{k}={v}" for k, v in run.data.params.items()]
    parts += [f"{k}={v}" for k, v in run.data.metrics.items()]
    parts += [
        f"{k}={v}" for k, v in run.data.tags.items() if not k.startswith("mlflow.")
    ]
    return " ".join(parts)


def test_mlflow_gets_ratios_and_counts_and_no_names_or_amounts(
    written: list[Written],
) -> None:
    fc.run("piero", TODAY)

    experiment = mlflow.get_experiment_by_name("spend-forecast")
    assert experiment is not None
    [run] = mlflow.search_runs([experiment.experiment_id], output_format="list")
    assert run.data.metrics["series"] == 1.0
    assert 0.0 <= run.data.metrics["baseline_used"] <= 1.0
    assert run.data.params["min_train_months"] == "9"
    text = _logged_text()
    assert CATEGORY not in text and SHOP not in text and "piero" not in text
    amounts = {f"{r.p50:.2f}" for r in written[0].forecasts}
    assert not any(amount in text for amount in amounts)
