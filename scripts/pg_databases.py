"""Create the throwaway PostgreSQL databases of the PR data diff (T29, ADR 0029).

`ci.yml`'s `pr-data-diff` job runs `dbt build` once for the base branch and once for
the PR; each build goes to its own database of the job's Postgres, so the two never
share a table and `scripts.data_diff` can attach both read-only.

    uv run python -m scripts.pg_databases pfp_diff_base pfp_diff_pr

Each name is dropped if it exists and created empty. Connects with the same
`PFP_PG_*` variables dbt uses; only names starting `pfp_diff_` are accepted, so this
can never drop the owner's data.
Exit code 0 on success, 2 for a refused name (matches `scripts/floor_guard.py`).
"""

import os
import re
import sys
from collections.abc import Sequence

import psycopg
from psycopg.conninfo import make_conninfo

# Only throwaway diff databases: `drop ... with (force)` must never reach another one.
_ALLOWED = re.compile(r"pfp_diff_[a-z0-9_]{1,40}")


def conninfo(database: str) -> str:
    """libpq connection string for `database`, from the `PFP_PG_*` variables."""
    return make_conninfo(
        dbname=database,
        host=os.environ.get("PFP_PG_HOST", "127.0.0.1"),
        port=os.environ.get("PFP_PG_PORT", "5432"),
        user=os.environ["PFP_PG_USER"],
        password=os.environ["PFP_PG_PASSWORD"],
    )


def main(argv: Sequence[str] | None = None) -> int:
    names = list(sys.argv[1:] if argv is None else argv)
    refused = [n for n in names if not _ALLOWED.fullmatch(n)]
    if refused or not names:
        print(
            "pg-databases: refusing "
            f"{refused or 'an empty list'}: names must match pfp_diff_<lowercase name>",
            file=sys.stderr,
        )
        return 2

    # `drop/create database` cannot run inside a transaction.
    with psycopg.connect(
        conninfo(os.environ["PFP_PG_DATABASE"]), autocommit=True
    ) as connection:
        for name in names:
            connection.execute(f'drop database if exists "{name}" with (force)')
            connection.execute(f'create database "{name}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
