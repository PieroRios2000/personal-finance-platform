"""Train the category classifier on the owner's own confirmed labels and compare it
against the rules-based baseline (T52, ADR 0044).

    uv run python -m scripts.train_category_model --user piero

Reads every labeled `(bank, description, category)` from `silver.category_labels` (the
same `PFP_PG_*` variables dbt uses), trains `categorization.model` on it, scores the
rules-based guesser on the exact same data, and prints both side by side: macro-F1 and
precision per category, never a description. Logs both to a local MLflow (params,
metrics; the fitted model itself only for the trained one) so a run can be compared to
an earlier one once there is more than one. The model file and the MLflow run both stay
under `~/finance-data/` -- never in the repo, never printed, never sent anywhere: a
fitted model's vocabulary is the owner's own real transaction text (ADR 0004)."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import psycopg
from psycopg.conninfo import make_conninfo

from categorization import model, rules
from categorization.model import DEFAULT_MODEL_PATH

# MLflow deprecated the plain filesystem store (3.x): sqlite is the current,
# supported local backend for a single-user project like this one.
DEFAULT_TRACKING_URI = f"sqlite:///{Path.home() / 'finance-data' / 'mlflow.db'}"

_QUERY = """
    select bank, description, category from silver.category_labels
    where user_id = %(user)s
"""


def _conninfo(database: str) -> str:
    return make_conninfo(
        dbname=database,
        host=os.environ.get("PFP_PG_HOST", "127.0.0.1"),
        port=os.environ.get("PFP_PG_PORT", "5432"),
        user=os.environ["PFP_PG_USER"],
        password=os.environ["PFP_PG_PASSWORD"],
    )


def fetch_labels(user_id: str) -> tuple[list[str], list[str]]:
    """(descriptions, categories), the owner's confirmed set, in one order."""
    with (
        psycopg.connect(_conninfo(os.environ["PFP_PG_DATABASE"])) as conn,
        conn.cursor() as cursor,
    ):
        cursor.execute(_QUERY, {"user": user_id})
        rows = cursor.fetchall()
    return [f"{bank} {description}" for bank, description, _c in rows], [
        str(category) for _b, _d, category in rows
    ]


def _report(label: str, metrics: model.Metrics) -> None:
    print(f"{label}: {metrics.examples} example(s), {metrics.categories} categorie(s)")
    print(f"{label}: macro-F1 = {metrics.macro_f1:.3f}")
    for category, precision in sorted(metrics.precision_by_category.items()):
        print(f"{label}: precision[{category}] = {precision:.3f}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER"))
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path(os.environ.get("PFP_CATEGORY_MODEL_PATH", DEFAULT_MODEL_PATH)),
    )
    args = parser.parse_args(argv)
    if not args.user:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    descriptions, categories = fetch_labels(args.user)
    try:
        pipeline, trained_metrics = model.train(descriptions, categories)
    except model.NotEnoughDataError as error:
        print(f"error: {error}", file=sys.stderr)
        print(
            "label more descriptions first (make export-category-labels)",
            file=sys.stderr,
        )
        return 1
    rules_metrics = model.score_rules(descriptions, categories, rules.guess)

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    with mlflow.start_run(run_name="category-classifier"):
        mlflow.log_params({"analyzer": "char_wb", "ngram_range": "(2, 4)"})
        mlflow.log_metrics(
            {
                "trained_macro_f1": trained_metrics.macro_f1,
                "rules_macro_f1": rules_metrics.macro_f1,
                "examples": float(trained_metrics.examples),
                "categories": float(trained_metrics.categories),
            }
        )
        mlflow.sklearn.log_model(pipeline, name="model")

        _report("model", trained_metrics)
        _report("rules", rules_metrics)
        won = "model" if trained_metrics.macro_f1 > rules_metrics.macro_f1 else "rules"
        print(f"the {won} baseline scores higher on this data")

        args.model_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        joblib.dump(pipeline, args.model_path.with_suffix(".joblib"))
        args.model_path.with_suffix(".joblib").chmod(0o600)
        print(f"model saved to {args.model_path.with_suffix('.joblib')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
