"""Export the labeling file for transaction categorization (T51, ADR 0043).

    uv run python -m scripts.export_category_labels --user piero [--out PATH]

Reads gold (the same `PFP_PG_*` variables dbt uses, connected directly -- this runs on
the owner's own machine, never in a container), groups every non-internal-transfer
movement by (bank, normalized description), and writes one row per group with a guess
already filled into `category`: the trained classifier's (T52) once one has been saved
(`make train-category-model`) and is confident enough (its own calibrated threshold,
`categorization.model.choose_confidence_threshold`), the cold-start rules-based
guesser (`categorization/rules.py`) otherwise -- the same "propose, never decide"
shape either way (ADR 0043). Open the file, fix the rows the guess got wrong, save,
then `make import-category-labels`. Never prints a description or an amount; only
counts."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from categorization.labels import write_template
from categorization.model import DEFAULT_MODEL_PATH as _MODEL_PATH_STEM
from categorization.model import Bundle
from categorization.model import load as load_model
from categorization.model import suggest as suggest_from_model
from categorization.rules import guess

DEFAULT_OUT = Path.home() / "finance-data" / "manual" / "categorias-transacciones.xlsx"
DEFAULT_MODEL_PATH = _MODEL_PATH_STEM.with_suffix(".joblib")

_QUERY = """
    select bank, description, count(*) as movements
    from gold.fact_transactions
    where user_id = %(user)s and not is_internal_transfer
    group by bank, description
    order by movements desc
"""


def _conninfo(database: str) -> str:
    return make_conninfo(
        dbname=database,
        host=os.environ.get("PFP_PG_HOST", "127.0.0.1"),
        port=os.environ.get("PFP_PG_PORT", "5432"),
        user=os.environ["PFP_PG_USER"],
        password=os.environ["PFP_PG_PASSWORD"],
    )


def fetch_groups(user_id: str) -> list[tuple[str, str, int]]:
    """(bank, description, movements), one row per group, gold-side only."""
    with (
        psycopg.connect(_conninfo(os.environ["PFP_PG_DATABASE"])) as conn,
        conn.cursor() as cursor,
    ):
        cursor.execute(_QUERY, {"user": user_id})
        return [(str(b), str(d), int(n)) for b, d, n in cursor.fetchall()]


def _suggest(description: str, bundle: Bundle | None) -> str:
    """The trained model's prediction once one has been loaded and its confidence
    clears the calibrated threshold, the rules-based guesser's otherwise (no bundle
    yet, or the model isn't confident enough -- `categorization.model.suggest`)."""
    if bundle is None:
        return guess(description)
    return suggest_from_model(bundle, description, guess)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path(os.environ.get("PFP_CATEGORY_MODEL_PATH", DEFAULT_MODEL_PATH)),
    )
    args = parser.parse_args(argv)
    if not args.user:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    groups = fetch_groups(args.user)
    if not groups:
        print("error: no movements found for that user in gold", file=sys.stderr)
        return 1
    bundle = load_model(args.model_path)
    rows = [
        (bank, description, movements, _suggest(description, bundle))
        for bank, description, movements in groups
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_template(args.out, rows)
    args.out.chmod(0o600)
    guessed = sum(1 for *_rest, suggested in rows if suggested != "Sin categorizar")
    source = (
        "the trained model (falling back to rules below its confidence threshold)"
        if bundle is not None
        else "the rules-based guesser"
    )
    print(f"wrote {args.out}: {len(rows)} description(s), {guessed} guessed already")
    print(f"suggestions came from {source}")
    print("Fix what the guess got wrong, save, then `make import-category-labels`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
