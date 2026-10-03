"""Drift monitoring for the category classifier (T55, ADR 0046).

    uv run python -m scripts.monitor_category_drift --user piero

Compares a REFERENCE window (every closed movement before the last `--current-days`
days) against a CURRENT window (the last `--current-days` days) with Evidently's data
drift preset, and writes an HTML report to `~/finance-data/reports/` -- never the repo.

What it looks at is derived shape only, never text: bank, currency, flow type, the
description's length and digit share, `log(1 + |amount|)`, and the label side -- the
category `gold.rpt_movements` assigned and whether it is the owner's confirmed label or
a model/rules proposal. The description itself is dropped in `build_features` before
anything reaches Evidently, so neither the report nor the printout can contain a real
merchant string (ADR 0004). Internal transfers are excluded, as everywhere else.

Read the result with the sample size in mind: with a few hundred movements per window a
flagged column is a prompt to look at the report, not a statistical verdict (ADR 0046).
Prints only counts, window dates and a drifted yes/no per column."""

import argparse
import datetime as dt
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from evidently import DataDefinition, Dataset, Report
from evidently.presets import DataDriftPreset
from psycopg.conninfo import make_conninfo

DEFAULT_REPORT_DIR = Path.home() / "finance-data" / "reports"
DEFAULT_CURRENT_DAYS = 90
DEFAULT_MIN_ROWS = 30

NUMERICAL_COLUMNS = ("description_length", "digit_share", "log_abs_amount")
CATEGORICAL_COLUMNS = ("bank", "currency", "flow_type", "category", "label_source")
FEATURE_COLUMNS = (*CATEGORICAL_COLUMNS, *NUMERICAL_COLUMNS)

_RAW_COLUMNS = (
    "date",
    "bank",
    "description",
    "currency",
    "flow_type",
    "amount",
    "category",
    "category_confirmed",
)

_QUERY = """
    select date, bank, description, currency, flow_type, amount::float8,
           category, category_confirmed
    from gold.rpt_movements
    where user_id = %(user)s and not is_internal_transfer
"""


class NotEnoughDataError(Exception):
    """A window is too small for a drift comparison to mean anything."""


@dataclass(frozen=True)
class DriftSummary:
    per_column: dict[str, bool]

    @property
    def total_columns(self) -> int:
        return len(self.per_column)

    @property
    def drifted_columns(self) -> int:
        return sum(self.per_column.values())


def _conninfo(database: str) -> str:
    return make_conninfo(
        dbname=database,
        host=os.environ.get("PFP_PG_HOST", "127.0.0.1"),
        port=os.environ.get("PFP_PG_PORT", "5432"),
        user=os.environ["PFP_PG_USER"],
        password=os.environ["PFP_PG_PASSWORD"],
    )


def movements_frame(rows: Sequence[Sequence[Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows), columns=list(_RAW_COLUMNS))
    frame["date"] = pd.to_datetime(frame["date"])
    frame["amount"] = frame["amount"].astype(float)
    return frame


def fetch_movements(user_id: str) -> pd.DataFrame:
    with (
        psycopg.connect(_conninfo(os.environ["PFP_PG_DATABASE"])) as conn,
        conn.cursor() as cursor,
    ):
        cursor.execute(_QUERY, {"user": user_id})
        return movements_frame(cursor.fetchall())


def build_features(movements: pd.DataFrame) -> pd.DataFrame:
    """The date (for splitting) plus `FEATURE_COLUMNS`; the description is dropped."""
    description = movements["description"].astype(str)
    length = description.str.len()
    digits = description.str.count(r"\d")
    features = pd.DataFrame(
        {
            "date": movements["date"],
            "bank": movements["bank"].astype(str),
            "currency": movements["currency"].astype(str),
            "flow_type": movements["flow_type"].astype(str),
            "category": movements["category"].astype(str),
            "label_source": np.where(
                movements["category_confirmed"], "confirmed", "predicted"
            ),
            "description_length": length.astype(float),
            "digit_share": (digits / length.where(length > 0, 1)).astype(float),
            "log_abs_amount": np.log1p(movements["amount"].abs()),
        }
    )
    return features


def split_windows(
    features: pd.DataFrame, *, current_days: int, min_rows: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(reference, current) by date, both without the `date` column."""
    if features.empty:
        raise NotEnoughDataError("no movements at all")
    cutoff = features["date"].max() - pd.Timedelta(days=current_days)
    is_current = features["date"] > cutoff
    reference = features[~is_current].drop(columns="date").reset_index(drop=True)
    current = features[is_current].drop(columns="date").reset_index(drop=True)
    for name, window in (("reference", reference), ("current", current)):
        if len(window) < min_rows:
            raise NotEnoughDataError(
                f"the {name} window has {len(window)} movement(s), need at least "
                f"{min_rows} (current window = last {current_days} day(s))"
            )
    return reference, current


def _dataset(frame: pd.DataFrame) -> Dataset:
    definition = DataDefinition(
        numerical_columns=list(NUMERICAL_COLUMNS),
        categorical_columns=list(CATEGORICAL_COLUMNS),
    )
    return Dataset.from_pandas(frame[list(FEATURE_COLUMNS)], data_definition=definition)


def _is_drifted(config: dict[str, Any], value: float) -> bool:
    """Evidently's p-value tests drift below the threshold; its distance tests above."""
    if "p_value" in str(config.get("method", "")):
        return bool(value < config["threshold"])
    return bool(value > config["threshold"])


def write_report(
    reference: pd.DataFrame, current: pd.DataFrame, output: Path
) -> DriftSummary:
    snapshot = Report([DataDriftPreset()]).run(_dataset(current), _dataset(reference))
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot.save_html(str(output))
    output.chmod(0o600)
    per_column = {
        metric["config"]["column"]: _is_drifted(metric["config"], metric["value"])
        for metric in snapshot.dict()["metrics"]
        if metric["config"]["type"].endswith("ValueDrift")
    }
    return DriftSummary(per_column=per_column)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER"))
    parser.add_argument("--current-days", type=int, default=DEFAULT_CURRENT_DAYS)
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.user:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    features = build_features(fetch_movements(args.user))
    try:
        reference, current = split_windows(
            features, current_days=args.current_days, min_rows=args.min_rows
        )
    except NotEnoughDataError as error:
        print(f"error: not enough data to compare: {error}", file=sys.stderr)
        return 1

    output = args.output or DEFAULT_REPORT_DIR / (
        f"category-drift-{dt.date.today().isoformat()}.html"
    )
    summary = write_report(reference, current, output)

    print(f"reference window: {len(reference)} movement(s); current: {len(current)}")
    print(
        f"drifted columns: {summary.drifted_columns} of {summary.total_columns} "
        f"({summary.drifted_columns / summary.total_columns:.0%})"
    )
    for column, drifted in sorted(summary.per_column.items()):
        print(f"drift[{column}] = {'yes' if drifted else 'no'}")
    print(
        "small windows: a 'yes' is a prompt to open the report, not a verdict "
        "(ADR 0046)"
    )
    print(f"report saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
