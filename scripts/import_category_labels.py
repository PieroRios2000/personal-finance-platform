"""Import the completed category-labels file into bronze (T51, ADR 0043).

    uv run python -m scripts.import_category_labels PATH --user piero

Reads the workbook `export_category_labels.py` wrote and the owner filled in, checks
every row's category is one of the fixed list, and replaces that user's whole set of
labels in bronze (`lakehouse.bronze.replace_category_labels`). Problems are reported as
row numbers only, never a description or a category value that isn't on the list."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from categorization.labels import read_completed
from lakehouse import bronze
from lakehouse.storage import MissingLakehouseURIError, lakehouse_uri


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--user", required=True)
    args = parser.parse_args(argv)

    if not args.workbook.exists():
        print("error: workbook not found", file=sys.stderr)
        return 2
    try:
        lakehouse_uri()
    except MissingLakehouseURIError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    rows, problems = read_completed(args.workbook)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print("nothing was written", file=sys.stderr)
        return 1

    bronze.replace_category_labels(args.user, rows)
    trusted = sum(1 for *_rest, is_trusted in rows if is_trusted)
    print(f"Categorias: {len(rows)} label(s) written (replaces the previous set).")
    print(
        f"{trusted} reviewed (corrected, or the guesser had no opinion), "
        f"{len(rows) - trusted} accepted the guesser's suggestion as is."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
