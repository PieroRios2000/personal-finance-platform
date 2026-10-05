"""Forecast the next three months of spending per category and currency (T59).

    uv run python -m scripts.forecast --user piero

Reads gold in a read-only session (the same `PFP_PG_*` variables dbt uses), takes the
closed months only, leaves out the charges the owner's plan calls fixed or ignored,
backtests five simple models against a trailing median per series and writes the
forecasts and the per-series quality to bronze, replacing this user's run for the last
closed month (ADR 0048, spec 4.2). dbt builds silver and gold from there
(`make forecast` runs it). Logs ratios and counts to MLflow, never a name or an amount,
and prints counts only."""

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import mlflow
import psycopg
from psycopg.conninfo import make_conninfo

from forecasting import backtest
from forecasting.candidates import CANDIDATES
from forecasting.series import TOTAL, Series, add_months, build_series
from lakehouse import bronze
from scripts.export_plan import fetch_monthly_spend
from scripts.pg_databases import conninfo

DEFAULT_TRACKING_URI = f"sqlite:///{Path.home() / 'finance-data' / 'mlflow.db'}"
EXPERIMENT = "spend-forecast"


def fetch_plan_exclusions(user_id: str) -> set[tuple[str, str, str]] | None:
    """(bank, description, currency) of the plan's fixed and ignored items, or None
    when no plan has been imported (silver is empty or not built yet)."""
    read_only = make_conninfo(
        conninfo(os.environ["PFP_PG_DATABASE"]),
        options="-c default_transaction_read_only=on",
    )
    query = """
        select bank, description, currency, kind
        from silver.plan_fixed_items
        where user_id = %(user)s
    """
    try:
        with psycopg.connect(read_only) as connection, connection.cursor() as cursor:
            cursor.execute(query, {"user": user_id})
            rows = cursor.fetchall()
    except psycopg.errors.UndefinedTable:
        return None
    if not rows:
        return None
    return {
        (str(b), str(d), str(c))
        for b, d, c, kind in rows
        if kind in ("fixed", "ignore")
    }


def _rows(
    fits: Sequence[backtest.SeriesFit],
) -> tuple[list[bronze.ForecastRow], list[bronze.ForecastSeriesRow]]:
    forecasts: list[bronze.ForecastRow] = []
    quality: list[bronze.ForecastSeriesRow] = []
    for fit in fits:
        forecasts += [
            bronze.ForecastRow(
                "forecast",
                fit.category,
                fit.currency,
                p.target_month,
                p.horizon,
                fit.model,
                p.p10,
                p.p50,
                p.p90,
                None,
            )
            for p in fit.future
        ]
        forecasts += [
            bronze.ForecastRow(
                "backtest",
                fit.category,
                fit.currency,
                b.target_month,
                1,
                fit.model,
                b.p10,
                b.p50,
                b.p90,
                b.actual,
            )
            for b in fit.past
        ]
        quality.append(
            bronze.ForecastSeriesRow(
                fit.category,
                fit.currency,
                fit.model,
                fit.baseline_used,
                fit.low_history,
                fit.n_months,
                fit.n_origins,
                fit.mae_rel,
                fit.coverage,
            )
        )
    return forecasts, quality


def _log_to_mlflow(
    fits: Sequence[backtest.SeriesFit], series: Sequence[Series]
) -> dict[str, float]:
    """Ratios and counts only (ADR 0004): no category, description or amount."""
    pairs = [(f, s) for f, s in zip(fits, series, strict=True) if s.category != TOTAL]
    weights = [float(s.values[-backtest.LEVEL_MONTHS :].sum()) for _f, s in pairs]
    metrics = backtest.summarize([f for f, _s in pairs], weights)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    experiment = mlflow.get_experiment_by_name(EXPERIMENT)
    experiment_id = (
        experiment.experiment_id if experiment else mlflow.create_experiment(EXPERIMENT)
    )
    with mlflow.start_run(experiment_id=experiment_id, run_name="spend-forecast"):
        mlflow.log_params(
            {
                "min_train_months": backtest.MIN_TRAIN,
                "horizons": backtest.HORIZONS,
                "candidates": ",".join(CANDIDATES),
                "min_improvement": backtest.MIN_IMPROVEMENT,
                "min_win_rate": backtest.MIN_WIN_RATE,
                "min_errors": backtest.MIN_ERRORS,
                "interval": f"p{round(backtest.LOW_QUANTILE * 100)}"
                f"-p{round(backtest.HIGH_QUANTILE * 100)}",
            }
        )
        mlflow.log_metrics(metrics)
    return metrics


def run(user_id: str, today: date) -> int:
    first_open_month = today.replace(day=1)
    run_month = add_months(first_open_month, -1)

    spending = fetch_monthly_spend(user_id)
    if not spending:
        print("error: no spending found for that user in gold", file=sys.stderr)
        return 1
    excluded = fetch_plan_exclusions(user_id)
    if excluded is None:
        print(
            "no plan imported: every charge is treated as variable (make import-plan)"
        )
    series = list(
        build_series(
            spending, first_open_month=first_open_month, excluded=excluded or set()
        ).values()
    )
    if not series:
        print("error: no closed month to forecast from", file=sys.stderr)
        return 1

    fits = backtest.fit_all(series)
    forecasts, quality = _rows(fits)
    bronze.replace_forecast_run(user_id, run_month, forecasts, quality)
    metrics = _log_to_mlflow(fits, series)

    print(
        f"forecast for the {len(fits)} series ({int(metrics['series'])} categories "
        f"plus totals) from {run_month:%Y-%m}: {len(forecasts)} forecast row(s) written"
    )
    print(
        f"{int(metrics['baseline_used'])} of {int(metrics['series'])} categories "
        f"keep the median baseline, {int(metrics['low_history'])} have little history"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER"))
    args = parser.parse_args(argv)
    if not args.user:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2
    return run(args.user, date.today())


if __name__ == "__main__":
    sys.exit(main())
