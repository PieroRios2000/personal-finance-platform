"""Prints bronze.statements' current row count (T21, ADR 0021).

`ephemeral-integration` (`.github/workflows/ci.yml`) compares this script's
output before and after a second `dagster asset materialize --select '*'`
pass to prove the whole pipeline is idempotent. Grepping the CLI's own
stdout for the bronze asset's report text -- the mechanism the pre-T21
`pfp ingest`-based check used -- is not reliable here: a multi-asset
`dagster asset materialize` does not stream a step's own
`context.log.info()` output to stdout the way a single-asset selection
does (confirmed by reproducing it directly), so this reads the real data
instead.

    uv run python -m scripts.count_bronze_statements
"""

from deltalake import DeltaTable

from lakehouse.storage import storage_options, table_uri


def main() -> int:
    uri = table_uri("statements")
    options = storage_options()
    count = (
        DeltaTable(uri, storage_options=options).to_pyarrow_table().num_rows
        if DeltaTable.is_deltatable(uri, storage_options=options)
        else 0
    )
    print(count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
