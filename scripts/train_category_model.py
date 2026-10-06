"""Train the category classifier on the owner's own confirmed labels and compare it
against the rules-based baseline (T52, ADR 0044).

    uv run python -m scripts.train_category_model --user piero

Reads every labeled `(bank, description, category, is_trusted)` from
`silver.category_labels` (the same `PFP_PG_*` variables dbt uses), trains
`categorization.model` on the whole set (more data makes a better saved model), and
reports two comparisons side by side, never a description:

- **all labels** -- every row, including ones where the owner just accepted the
  rules-based guesser's own suggestion unreviewed.
- **trusted labels only** -- rows the owner actually reviewed (corrected, or the
  guesser had no opinion to begin with, `categorization.labels.read_completed`). The
  rules baseline measured against labels it proposed itself is circular and can look
  better than it is; this second comparison is the honest one (reviewer feedback,
  2026-09-27).

Also reports the number of cross-validation folds each score is averaged over (few
labels means as few as 2, worth less trust than 5) and the confidence threshold chosen
for the saved model (`categorization.model.choose_confidence_threshold`), below which
`scripts/export_category_labels.py` falls back to the rules-based guesser instead of
trusting an uncalibrated probability. The threshold itself is reported; the macro-F1
used internally to choose it is not, on purpose (that number is optimistic by
construction -- see `choose_confidence_threshold`'s own docstring). The four macro-F1s
this script does report (model/rules x all/trusted) are the only ones honest enough to
quote anywhere, including a CV or an interview.

Logs everything to a local MLflow (params, metrics; the fitted bundle itself) so a run
can be compared to an earlier one once there is more than one. The model file and the
MLflow run both stay under `~/finance-data/` -- never in the repo, never printed, never
sent anywhere: a fitted model's vocabulary is the owner's own real transaction text
(ADR 0004)."""

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
    select bank, description, category, is_trusted from silver.category_labels
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


def fetch_labels(user_id: str) -> tuple[list[str], list[str], list[bool]]:
    """(descriptions, categories, trusted), the owner's confirmed set, in one order."""
    with (
        psycopg.connect(_conninfo(os.environ["PFP_PG_DATABASE"])) as conn,
        conn.cursor() as cursor,
    ):
        cursor.execute(_QUERY, {"user": user_id})
        rows = cursor.fetchall()
    return (
        [f"{bank} {description}" for bank, description, _c, _t in rows],
        [str(category) for _b, _d, category, _t in rows],
        [bool(trusted) for _b, _d, _c, trusted in rows],
    )


def _report(label: str, metrics: model.Metrics) -> None:
    print(
        f"{label}: {metrics.examples} example(s), {metrics.categories} categorie(s), "
        f"{metrics.folds} fold(s)"
    )
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

    descriptions, categories, trusted = fetch_labels(args.user)
    try:
        pipeline, trained_metrics = model.train(descriptions, categories)
        threshold, threshold_folds = model.choose_confidence_threshold(
            descriptions, categories, rules.guess
        )
    except model.NotEnoughDataError as error:
        print(f"error: {error}", file=sys.stderr)
        print(
            "label more descriptions first (make export-category-labels)",
            file=sys.stderr,
        )
        return 1
    rules_metrics = model.score_rules(descriptions, categories, rules.guess)

    trusted_descriptions = [d for d, t in zip(descriptions, trusted, strict=True) if t]
    trusted_categories = [c for c, t in zip(categories, trusted, strict=True) if t]
    trusted_model_metrics: model.Metrics | None = None
    trusted_rules_metrics: model.Metrics | None = None
    try:
        _trusted_pipeline, trusted_model_metrics = model.train(
            trusted_descriptions, trusted_categories
        )
        trusted_rules_metrics = model.score_rules(
            trusted_descriptions, trusted_categories, rules.guess
        )
    except model.NotEnoughDataError as error:
        print(
            f"trusted-only comparison skipped: {error} "
            f"({len(trusted_descriptions)} of {len(descriptions)} labels are "
            f"trusted -- see the import's own corrected/accepted count)"
        )

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    with mlflow.start_run(run_name="category-classifier"):
        mlflow.log_params(
            {
                "analyzer": "char_wb",
                "ngram_range": "(2, 4)",
                "confidence_threshold": threshold,
                "threshold_folds": threshold_folds,
            }
        )
        metrics_to_log = {
            "trained_macro_f1": trained_metrics.macro_f1,
            "trained_folds": float(trained_metrics.folds),
            "rules_macro_f1": rules_metrics.macro_f1,
            "examples": float(trained_metrics.examples),
            "categories": float(trained_metrics.categories),
            "trusted_examples": float(len(trusted_descriptions)),
        }
        if trusted_model_metrics is not None and trusted_rules_metrics is not None:
            metrics_to_log["trusted_trained_macro_f1"] = trusted_model_metrics.macro_f1
            metrics_to_log["trusted_rules_macro_f1"] = trusted_rules_metrics.macro_f1
        mlflow.log_metrics(metrics_to_log)
        mlflow.sklearn.log_model(pipeline, name="model")

        _report("model (all labels)", trained_metrics)
        _report("rules (all labels)", rules_metrics)
        won = "model" if trained_metrics.macro_f1 > rules_metrics.macro_f1 else "rules"
        print(f"the {won} baseline scores higher on all labels")
        if trusted_model_metrics is not None and trusted_rules_metrics is not None:
            _report("model (trusted only)", trusted_model_metrics)
            _report("rules (trusted only)", trusted_rules_metrics)
            trusted_won = (
                "model"
                if trusted_model_metrics.macro_f1 > trusted_rules_metrics.macro_f1
                else "rules"
            )
            print(
                f"the {trusted_won} baseline scores higher on trusted-only labels "
                "(the honest comparison -- the rules-only figure above can be "
                "inflated by labels the rules proposed themselves)"
            )
        print(
            f"confidence threshold: {threshold:.3f} "
            f"({threshold_folds} fold(s)) -- export_category_labels falls back to "
            "rules below this"
        )

        bundle = model.Bundle(
            pipeline=pipeline, confidence_threshold=threshold, trained_for=args.user
        )
        args.model_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        joblib.dump(bundle, args.model_path.with_suffix(".joblib"))
        args.model_path.with_suffix(".joblib").chmod(0o600)
        print(f"model saved to {args.model_path.with_suffix('.joblib')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
