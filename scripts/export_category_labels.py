"""Export the labeling file for transaction categorization (T51, ADR 0043).

    uv run python -m scripts.export_category_labels --user piero [--out PATH]

Reads gold (the same `PFP_PG_*` variables dbt uses, connected directly -- this runs on
the owner's own machine, never in a container), groups every non-internal-transfer
movement by (bank, normalized description), and writes one row per group with a
cold-start guess (`categorization/rules.py`) already filled into `category`. Open the
file, fix the rows the guess got wrong, save, then `make import-category-labels`.
Never prints a description or an amount; only counts."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from categorization.labels import write_template
from categorization.rules import guess

DEFAULT_OUT = Path.home() / "finance-data" / "manual" / "categorias-transacciones.xlsx"

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not args.user:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    groups = fetch_groups(args.user)
    if not groups:
        print("error: no movements found for that user in gold", file=sys.stderr)
        return 1
    rows = [
        (bank, description, movements, guess(description))
        for bank, description, movements in groups
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_template(args.out, rows)
    args.out.chmod(0o600)
    guessed = sum(1 for *_rest, suggested in rows if suggested != "Sin categorizar")
    print(f"wrote {args.out}: {len(rows)} description(s), {guessed} guessed already")
    print("Fix what the guess got wrong, save, then `make import-category-labels`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
