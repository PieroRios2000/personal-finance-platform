"""Export the savings-plan workbook: fixed-expense candidates and the goal (T56).

    uv run python -m scripts.export_plan --user piero [--out PATH]

Reads gold (the same `PFP_PG_*` variables dbt uses, in a read-only session; this runs
on the owner's own machine, never in a container), builds the monthly spend of every
(bank, description, currency) over the closed months, and writes the workbook the
owner fills in: which expenses are fixed, the goal in dollars, the exchange rate and
the emergency-fund settings (ADR 0048, spec 4.1). Run again, it keeps what the owner
already chose and only refreshes or adds rows. Never prints a description or an
amount; only counts."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from forecasting.fixed_expenses import MonthlySpend, detect_candidates
from forecasting.plan_file import merge, read_plan, write_plan
from scripts.pg_databases import conninfo

DEFAULT_OUT = Path.home() / "finance-data" / "plan" / "plan-de-ahorro.xlsx"

_QUERY = """
    select
        bank,
        description,
        currency,
        category,
        date_trunc('month', date)::date as month,
        sum(-signed_amount) as amount
    from gold.rpt_movements
    where user_id = %(user)s
      and flow_type = 'egreso'
      and not is_internal_transfer
      and category <> 'Ingresos'
    group by 1, 2, 3, 4, 5
"""


def fetch_monthly_spend(user_id: str) -> list[MonthlySpend]:
    """One row per (bank, description, currency, category, month), gold-side only."""
    read_only = make_conninfo(
        conninfo(os.environ["PFP_PG_DATABASE"]),
        options="-c default_transaction_read_only=on",
    )
    with psycopg.connect(read_only) as connection, connection.cursor() as cursor:
        cursor.execute(_QUERY, {"user": user_id})
        return [
            MonthlySpend(str(b), str(d), str(c), str(k), m, float(a))
            for b, d, c, k, m, a in cursor.fetchall()
        ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not args.user:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    rows = fetch_monthly_spend(args.user)
    if not rows:
        print("error: no spending found for that user in gold", file=sys.stderr)
        return 1

    candidates = detect_candidates(rows)
    previous = read_plan(args.out) if args.out.exists() else None
    plan = merge(candidates, previous)

    args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Written beside the target and renamed over it, so a crash mid-write can never
    # destroy the choices the owner already made in the existing file.
    staging = args.out.with_name(args.out.name + ".tmp")
    write_plan(staging, plan)
    staging.chmod(0o600)
    staging.replace(args.out)

    fixed = sum(1 for item in plan.items if item.proposed_kind == "fixed")
    kept = 0 if previous is None else len(previous.items)
    print(
        f"wrote {args.out}: {len(plan.items)} candidate(s), "
        f"{fixed} proposed as fixed, {len(plan.items) - fixed} as variable"
    )
    if previous is not None:
        print(f"re-export: {kept} existing row(s) kept their owner choices")
    print("Fill kind/expected_amount and the Meta sheet, save. Import comes with T57.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
