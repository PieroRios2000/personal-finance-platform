"""Batch-categorize new movements at ingest time (T54, ADR 0045).

Once a trained model exists (`make train-category-model`), every `(bank,
description)` the owner hasn't confirmed a category for yet gets an automatic
prediction, written to `bronze.category_predictions`. `gold.rpt_movements` picks it
up as a *proposed* category (`category_confirmed = false`) -- never silently
promoted to a confirmed one, the same "propose, never assign silently" shape ADR
0043 already established for the manual labeling flow.

Runs automatically as the last step of `pfp ingest` (`ingestion.cli._run_ingest`)
and of the Dagster `bronze` asset (`orchestration.assets.bronze`) -- both call
`run()` directly, the same "shared primitive, no cross-import between the two
entry points" shape `orchestration.assets.bronze` already uses for
`ingestion.organizer.organize`/`lakehouse.bronze.write_statement`.

Reads and writes bronze only -- no `PFP_PG_*` needed, so this never blocks on
Postgres being reachable at ingest time. A description belonging to an internal
transfer gets predicted too: bronze has no `is_internal_transfer` flag yet (that's
computed later, in silver), so there is no cheap way to exclude it here. Harmless
waste at this project's scale (`gold.rpt_movements`'s own join only ever surfaces a
prediction for a real spending/income row, never an internal transfer, regardless
of whether one was computed for it).

Never prints, logs or returns a description: only counts, same discipline as every
other categorization script."""

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from categorization.model import DEFAULT_MODEL_PATH, load, suggest
from categorization.rules import guess
from lakehouse import bronze


@dataclass(frozen=True)
class Report:
    """Counts only, safe to print -- see this module's own docstring."""

    total_descriptions: int
    already_labeled: int
    predicted: int
    has_model: bool


def run(user_id: str, model_path: Path | None = None) -> Report:
    """Predicts a category for every `(bank, description)` `user_id` has in bronze
    transactions that isn't already in their confirmed labels, using the saved
    model if one exists. Writes the whole set to `bronze.category_predictions`
    (replaced each run, same whole-set-replace shape as
    `lakehouse.bronze.replace_category_labels`) -- always reflects the latest
    trained model, cheap to recompute at this project's scale (tens to low
    hundreds of distinct descriptions).

    No model for this user: reports it (`has_model=False`) and clears any stale
    predictions from a model that may have existed before, rather than leaving
    outdated ones in place. "No model for this user" covers a model trained for
    someone else (`Bundle.trained_for`) or saved before that field existed: the
    one installed model is fitted on one person's labels and text, so another
    person's upload (`make ingest-uploads`) never gets its proposals."""
    path = (model_path or DEFAULT_MODEL_PATH).with_suffix(".joblib")
    bundle = load(path)

    descriptions = bronze.distinct_bank_descriptions(user_id)
    labeled = bronze.labeled_bank_descriptions(user_id)
    to_predict = [pair for pair in descriptions if pair not in labeled]

    if bundle is None or bundle.trained_for != user_id:
        bronze.replace_category_predictions(user_id, [])
        return Report(
            total_descriptions=len(descriptions),
            already_labeled=len(descriptions) - len(to_predict),
            predicted=0,
            has_model=False,
        )

    predictions = [
        (bank, description, suggest(bundle, f"{bank} {description}", guess))
        for bank, description in to_predict
    ]
    bronze.replace_category_predictions(user_id, predictions)
    return Report(
        total_descriptions=len(descriptions),
        already_labeled=len(descriptions) - len(to_predict),
        predicted=len(predictions),
        has_model=True,
    )


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

    report = run(args.user, model_path=args.model_path)
    if not report.has_model:
        print(
            "Categorias: no model trained for this user "
            "(make train-category-model); nothing predicted."
        )
        return 0
    print(
        f"Categorias: {report.predicted} new description(s) predicted, "
        f"{report.already_labeled} already had the owner's own label "
        f"({report.total_descriptions} total)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
