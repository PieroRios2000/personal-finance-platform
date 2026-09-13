---
type: component
phase: 1
status: built
task: T14
---

# Lakehouse (bronze)

Writes parsed, reconciled statements to append-only Delta tables, partitioned by `user_id`
(ADR 0009), located via one `LAKEHOUSE_URI` environment variable that works the same whether
it points at local S3 (SeaweedFS, ADR 0003) or a plain disk path in unit tests (ADR 0006).

## Pieces

| Piece | What it does |
|---|---|
| [`lakehouse/storage.py`](../../lakehouse/storage.py) | `lakehouse_uri()` reads `LAKEHOUSE_URI`, raising `MissingLakehouseURIError` if it's unset. `storage_options()` returns `None` for a plain path, or the S3-compatible options `deltalake` needs for a non-AWS, plain-HTTP endpoint like SeaweedFS when it starts with `s3://`. `table_uri(name)` builds `<LAKEHOUSE_URI>/bronze/<name>` |
| [`lakehouse/bronze.py`](../../lakehouse/bronze.py) | `is_ingested(user_id, file_sha256)`: true if that file is already recorded for that user. `write_statement(statement, file_sha256)`: appends the statement's transactions to `bronze/transactions`, a summary row to `bronze/statements`, and a record to `bronze/ingested_files` — always appends; the caller checks `is_ingested()` first (see [CLI](cli.md)'s `pfp ingest`) |
| [`ingestion/organizer.py`](../../ingestion/organizer.py)'s `ArchivedItem` | Carries the already-parsed `Statement` and its `sha256` (T14 extension) so `pfp ingest` writes to bronze without re-opening, re-decrypting or re-parsing a file `organize()` already handled |

## A real bug found while building this

pyarrow's `Table.from_pylist()` infers a `decimal128` precision from each batch's own values.
Two separate `write_deltalake(..., mode="append")` calls — one with `Decimal("12.34")`, a
later one with `Decimal("123456.78")` — infer different precisions per batch
(`Decimal128(4, 2)` then `Decimal128(8, 2)`), and `deltalake` rejects the second append outright
(`SchemaMismatchError: Cannot cast field amount from Decimal128(8, 2) to Decimal128(4, 2)`),
reproduced directly against the installed `deltalake==1.6.3`. Fixed with one fixed, explicit
pyarrow schema (`decimal128(18, 2)`) passed to every `from_pylist()` call, so every append
agrees on the money columns' type regardless of what values that particular batch happens to
hold. Covered by a dedicated regression test
([`tests/test_bronze.py`](../../tests/test_bronze.py)).

## How to use it and how to verify it

```bash
uv run pfp ingest --user piero   # organizes the inbox, then writes new statements to bronze
```

- Unit tests point `LAKEHOUSE_URI` at a `tmp_path` (disk, no S3 needed):
  [`tests/test_bronze.py`](../../tests/test_bronze.py),
  [`tests/test_storage.py`](../../tests/test_storage.py),
  [`tests/test_cli.py`](../../tests/test_cli.py).
- An `integration`-marked test
  ([`tests/test_bronze_integration.py`](../../tests/test_bronze_integration.py)) writes to and
  reads from real local S3 (`make poc-up`), then deletes its own rows afterwards
  (`DeltaTable.delete`) so the shared SeaweedFS volume doesn't grow across runs. Deselected by
  default (`pytest -m integration` to run it); see CONSTRAINTS.md's exceptions table for why.
- Two-users isolation verified physically, not just logically: writing `piero` and `ana` lands
  each under their own `user_id=<id>` partition directory, and deleting `ana`'s partition files
  on disk leaves `piero`'s data fully readable.

## Related

- [ADR 0006: Lake location by URI](../decisions/0006-lake-location-by-uri.md) — the storage
  design and the decimal-precision fix, in full.
- [ADR 0002: DuckDB + delta-rs before Spark](../decisions/0002-duckdb-and-delta-rs-before-spark.md)
- [ADR 0003: Local S3 with SeaweedFS](../decisions/0003-local-s3-with-seaweedfs.md)
- [ADR 0009: Several users, several accounts](../decisions/0009-multi-user-multi-account-content-over-filename.md) —
  the `user_id` partitioning this component relies on.
- [CLI](cli.md) — `pfp ingest`, the only caller of `write_statement()`/`is_ingested()`.
- [Inbox organizer](inbox-organizer.md) — produces the `ArchivedItem`s `pfp ingest` writes.
- [Phase 1](../phases/phase-1.md)
