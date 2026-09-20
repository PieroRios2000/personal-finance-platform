"""data-diff: what dbt build produced on the base branch vs. the PR (T17b, ADR 0007).

`ci.yml`'s `pr-data-diff` job runs `dbt build` twice -- once checked out at the
base branch's commit, once at the PR's -- each against its own `LAKEHOUSE_URI`
prefix and its own on-disk DuckDB file (`dbt/profiles.yml`'s `PFP_DUCKDB_PATH`).
This module compares the two: row counts per model, a column/type diff, and a
bounded sample of differing rows (`EXCEPT` both ways) for whatever model exists
on both sides.

`connect()` attaches both files, read-only, into one in-memory connection
(`base` and `pr`), so every comparison below is a single-connection query --
the same reason `tests/test_data_diff.py` can build two small DuckDB files by
hand and never touch the real pipeline.

    uv run python -m scripts.data_diff --base BASE.duckdb --pr PR.duckdb

Prints Markdown to stdout; `ci.yml` appends it to `$GITHUB_STEP_SUMMARY`, the
same idiom the `changes` and `benchmarks` jobs already use. This check only
warns (T17b, unlike `ephemeral-integration`): it always exits 0 once it can
read both files, whatever the diff turns out to be -- a real base-vs-PR
difference is expected and informative, never a failure. Exit code 2 means it
could not even open the two databases (matches `scripts/floor_guard.py`'s
"0 clean, 2 could not run" convention).
"""

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb
from psycopg.conninfo import make_conninfo

# T29: silver and gold are both in the store, so both are compared; a schema
# neither side has is left out of the report.
SCHEMAS = ("silver", "gold")
DEFAULT_SCHEMA = "silver"
DEFAULT_SAMPLE_LIMIT = 5

# Fixed attached-database names: never user input, so no quoting concerns.
_BASE = "base"
_PR = "pr"


@dataclass(frozen=True)
class ColumnDiff:
    """A model's column shape, base vs. PR."""

    added: tuple[str, ...] = ()  # in the PR, not in base
    removed: tuple[str, ...] = ()  # in base, not in the PR
    type_changed: tuple[tuple[str, str, str], ...] = ()  # (column, base type, PR type)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.type_changed)


@dataclass(frozen=True)
class ModelDiff:
    """One dbt model's comparison. `base_rows`/`pr_rows` is None when the
    model doesn't exist on that side; the sample fields are then empty, since
    there is nothing on the other side to compare rows against."""

    name: str
    base_rows: int | None
    pr_rows: int | None
    columns: ColumnDiff
    sample_columns: tuple[str, ...] = ()
    sample_only_in_base: tuple[tuple[object, ...], ...] = ()
    sample_only_in_pr: tuple[tuple[object, ...], ...] = ()

    @property
    def has_changes(self) -> bool:
        return (
            self.base_rows != self.pr_rows
            or not self.columns.is_empty
            or bool(self.sample_only_in_base)
            or bool(self.sample_only_in_pr)
        )


def connect(base_path: Path | str, pr_path: Path | str) -> duckdb.DuckDBPyConnection:
    """One in-memory connection with both `.duckdb` files attached read-only,
    as `base` and `pr`. Raises `duckdb.Error` if either path can't be opened
    (missing file, or a file another process still has open for writing)."""
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{base_path}' AS {_BASE} (READ_ONLY)")
    con.execute(f"ATTACH '{pr_path}' AS {_PR} (READ_ONLY)")
    return con


def postgres_attach(alias: str, database: str) -> str:
    """`ATTACH` statement for one PostgreSQL database, read-only, from `PFP_PG_*`.
    The password is quoted for libpq and then for the SQL literal."""
    conninfo = make_conninfo(
        dbname=database,
        host=os.environ.get("PFP_PG_HOST", "127.0.0.1"),
        port=os.environ.get("PFP_PG_PORT", "5432"),
        user=os.environ["PFP_PG_USER"],
        password=os.environ["PFP_PG_PASSWORD"],
    )
    literal = conninfo.replace("'", "''")
    return f"ATTACH '{literal}' AS {alias} (TYPE postgres, READ_ONLY)"


def connect_postgres(base_database: str, pr_database: str) -> duckdb.DuckDBPyConnection:
    """One in-memory connection with both PostgreSQL databases attached read-only,
    as `base` and `pr`. Raises `duckdb.Error` if either cannot be reached."""
    con = duckdb.connect(":memory:")
    con.execute("INSTALL postgres")
    con.execute("LOAD postgres")
    con.execute(postgres_attach(_BASE, base_database))
    con.execute(postgres_attach(_PR, pr_database))
    return con


def _list_models(con: duckdb.DuckDBPyConnection, catalog: str, schema: str) -> set[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_catalog = ? AND table_schema = ?",
        [catalog, schema],
    ).fetchall()
    return {row[0] for row in rows}


def _columns(
    con: duckdb.DuckDBPyConnection, catalog: str, schema: str, table: str
) -> dict[str, str]:
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_catalog = ? AND table_schema = ? AND table_name = ? "
        "ORDER BY ordinal_position",
        [catalog, schema, table],
    ).fetchall()
    return dict(rows)


def _row_count(
    con: duckdb.DuckDBPyConnection, catalog: str, schema: str, table: str
) -> int:
    query = f'SELECT count(*) FROM "{catalog}"."{schema}"."{table}"'
    result = con.execute(query).fetchone()
    assert result is not None  # count(*) always returns exactly one row
    return int(result[0])


def _sample_except(
    con: duckdb.DuckDBPyConnection,
    left: str,
    right: str,
    schema: str,
    table: str,
    columns: Sequence[str],
    limit: int,
) -> tuple[tuple[object, ...], ...]:
    """Rows in `left.schema.table` with no match in `right.schema.table`,
    restricted to their common columns -- `EXCEPT` needs the same column list
    on both sides, and a column only one side has can never produce a match
    anyway."""
    projection = ", ".join(f'"{c}"' for c in columns)
    query = (
        f'SELECT {projection} FROM "{left}"."{schema}"."{table}" '
        f'EXCEPT SELECT {projection} FROM "{right}"."{schema}"."{table}" '
        f"LIMIT {limit}"
    )
    return tuple(con.execute(query).fetchall())


def diff_columns(
    base_columns: dict[str, str], pr_columns: dict[str, str]
) -> ColumnDiff:
    """Pure comparison of two `{column: type}` maps -- no database involved."""
    added = tuple(c for c in pr_columns if c not in base_columns)
    removed = tuple(c for c in base_columns if c not in pr_columns)
    type_changed = tuple(
        (c, base_columns[c], pr_columns[c])
        for c in base_columns
        if c in pr_columns and base_columns[c] != pr_columns[c]
    )
    return ColumnDiff(added=added, removed=removed, type_changed=type_changed)


def diff_model(
    con: duckdb.DuckDBPyConnection,
    schema: str,
    name: str,
    *,
    base_present: bool,
    pr_present: bool,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> ModelDiff:
    """Compares one model by name. A model missing from either side is
    reported (rows=None on that side), not an error: the other side's row
    count already says everything a column/row diff could add."""
    base_rows = _row_count(con, _BASE, schema, name) if base_present else None
    pr_rows = _row_count(con, _PR, schema, name) if pr_present else None

    columns = ColumnDiff()
    sample_columns: tuple[str, ...] = ()
    sample_only_in_base: tuple[tuple[object, ...], ...] = ()
    sample_only_in_pr: tuple[tuple[object, ...], ...] = ()

    if base_present and pr_present:
        base_columns = _columns(con, _BASE, schema, name)
        pr_columns = _columns(con, _PR, schema, name)
        columns = diff_columns(base_columns, pr_columns)

        common = tuple(c for c in base_columns if c in pr_columns)
        if common:
            sample_columns = common
            sample_only_in_base = _sample_except(
                con, _BASE, _PR, schema, name, common, sample_limit
            )
            sample_only_in_pr = _sample_except(
                con, _PR, _BASE, schema, name, common, sample_limit
            )

    return ModelDiff(
        name=name,
        base_rows=base_rows,
        pr_rows=pr_rows,
        columns=columns,
        sample_columns=sample_columns,
        sample_only_in_base=sample_only_in_base,
        sample_only_in_pr=sample_only_in_pr,
    )


def diff_all(
    con: duckdb.DuckDBPyConnection,
    schema: str = DEFAULT_SCHEMA,
    *,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> list[ModelDiff]:
    """Every model that exists on either side, base and PR compared."""
    base_models = _list_models(con, _BASE, schema)
    pr_models = _list_models(con, _PR, schema)
    return [
        diff_model(
            con,
            schema,
            name,
            base_present=name in base_models,
            pr_present=name in pr_models,
            sample_limit=sample_limit,
        )
        for name in sorted(base_models | pr_models)
    ]


def _render_sample(diff: ModelDiff) -> list[str]:
    lines = []
    header = ", ".join(diff.sample_columns)
    if diff.sample_only_in_base:
        lines.append(f"  - only in base ({header}):")
        lines += [f"    - {row}" for row in diff.sample_only_in_base]
    if diff.sample_only_in_pr:
        lines.append(f"  - only in PR ({header}):")
        lines += [f"    - {row}" for row in diff.sample_only_in_pr]
    return lines


def render_markdown(diffs: list[ModelDiff], schema: str | None = None) -> str:
    """The base-vs-PR comparison as Markdown for `$GITHUB_STEP_SUMMARY`."""
    where = f" -- `{schema}`" if schema else ""
    lines = [f"### data-diff: base vs. PR (T17b){where}", ""]

    # Distinct from "no changes": an empty `diffs` means neither side's dbt
    # build put a single model in the schema (e.g. both runs failed before
    # building anything), so nothing was actually compared -- `not any(...)`
    # over an empty list is vacuously True, and reporting that as "No
    # changes" would misrepresent a broken run as a clean one.
    if not diffs:
        lines.append(
            "No models found on either side -- nothing was compared "
            "(check the ingest/dbt build steps above)."
        )
        return "\n".join(lines) + "\n"

    if not any(d.has_changes for d in diffs):
        lines.append(
            "No changes: every model has the same row counts, columns and rows."
        )
        return "\n".join(lines) + "\n"

    for diff in diffs:
        if not diff.has_changes:
            lines.append(f"- `{diff.name}`: no changes")
            continue

        if diff.base_rows is None:
            lines.append(f"- `{diff.name}`: new model (PR: {diff.pr_rows} rows)")
            continue
        if diff.pr_rows is None:
            lines.append(
                f"- `{diff.name}`: removed model (base: {diff.base_rows} rows)"
            )
            continue

        lines.append(
            f"- `{diff.name}`: base {diff.base_rows} rows, PR {diff.pr_rows} rows"
        )
        if diff.columns.added:
            lines.append(f"  - columns added: {', '.join(diff.columns.added)}")
        if diff.columns.removed:
            lines.append(f"  - columns removed: {', '.join(diff.columns.removed)}")
        for column, base_type, pr_type in diff.columns.type_changed:
            lines.append(f"  - `{column}` type changed: {base_type} -> {pr_type}")
        lines += _render_sample(diff)

    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, help="base branch's .duckdb file")
    parser.add_argument("--pr", type=Path, help="PR's .duckdb file")
    parser.add_argument("--base-database", help="base branch's PostgreSQL database")
    parser.add_argument("--pr-database", help="PR's PostgreSQL database")
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=DEFAULT_SAMPLE_LIMIT,
        help=f"differing rows per model, per side (default {DEFAULT_SAMPLE_LIMIT})",
    )
    args = parser.parse_args(argv)

    files = (args.base, args.pr)
    databases = (args.base_database, args.pr_database)
    if all(files) == all(databases) or any(files) and any(databases):
        parser.error(
            "give either --base and --pr, or --base-database and --pr-database"
        )

    try:
        if all(files):
            con = connect(args.base, args.pr)
        else:
            con = connect_postgres(args.base_database, args.pr_database)
    except duckdb.Error as error:
        print(
            f"data-diff: could not open the base or the PR database: {error}",
            file=sys.stderr,
        )
        return 2

    by_schema = {
        schema: diff_all(con, schema, sample_limit=args.sample_limit)
        for schema in SCHEMAS
    }
    reports = [
        render_markdown(diffs, schema) for schema, diffs in by_schema.items() if diffs
    ]
    print("\n\n".join(reports) if reports else render_markdown([]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
