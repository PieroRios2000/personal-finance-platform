"""Import the completed savings-plan workbook into bronze (T57, ADR 0048).

    uv run python -m scripts.import_plan --user piero [--workbook PATH]

Reads the workbook `export_plan.py` wrote and the owner filled in, checks every row of
`Gastos fijos` and every field of `Meta` (including that `emergency_account` is an asset
account the lake knows), and replaces that user's whole plan in bronze
(`lakehouse.bronze.replace_plan`). All problems are listed at once, by row number or
field name, never by a value the owner typed; if there is any, nothing is written."""

import argparse
import os
import stat
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from forecasting.plan_file import read_plan
from forecasting.plan_import import check_plan
from lakehouse import bronze
from lakehouse.storage import MissingLakehouseURIError, lakehouse_uri
from scripts import export_plan

DEFAULT_WORKBOOK = export_plan.DEFAULT_OUT


def _make_private(path: Path) -> None:
    """Excel on Windows re-saves the file with default permissions; the plan holds the
    owner's own spending, so it goes back to 0600 (and says so)."""
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        path.chmod(0o600)
        print(
            "note: the workbook was readable by others; made it private",
            file=sys.stderr,
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER"))
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    args = parser.parse_args(argv)
    if not args.user:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2
    if not args.workbook.exists():
        print("error: workbook not found", file=sys.stderr)
        return 2
    _make_private(args.workbook)
    try:
        lakehouse_uri()
    except MissingLakehouseURIError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    problems: list[str] = []
    try:
        plan = read_plan(args.workbook, problems)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    goal, more = check_plan(
        plan,
        today=date.today(),
        asset_accounts=bronze.asset_account_names(args.user),
    )
    problems += more
    if problems or goal is None:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print("nothing was written", file=sys.stderr)
        return 1

    bronze.replace_plan(
        args.user,
        [
            bronze.PlanItemRow(
                bank=item.bank,
                description=item.description,
                currency=item.currency,
                category=item.category,
                months_seen=item.months_seen,
                typical_amount=item.typical_amount,
                proposed_kind=item.proposed_kind,
                kind=item.kind,
                expected_amount=item.expected_amount,
                note=item.note,
            )
            for item in plan.items
        ],
        bronze.PlanGoalRow(**vars(goal)),
    )
    kinds = Counter(item.kind for item in plan.items)
    print(
        f"Plan: {len(plan.items)} item(s) loaded (replaces the previous plan): "
        f"{kinds['fixed']} fixed, {kinds['variable']} variable, "
        f"{kinds['ignore']} ignore."
    )
    print("Meta validated: goal in dollars, rate and emergency fund. Run `make build`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
