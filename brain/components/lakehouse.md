---
type: component
phase: 1
status: built
task: T14, T14c
---

# Lakehouse (bronze)

Writes parsed, reconciled statements to append-only Delta tables, partitioned by `user_id`
(ADR 0009), located via one `LAKEHOUSE_URI` environment variable that works the same whether
it points at local S3 (SeaweedFS, ADR 0003) or a plain disk path in unit tests (ADR 0006).

## Pieces

| Piece | What it does |
|---|---|
| [`lakehouse/storage.py`](../../lakehouse/storage.py) | `lakehouse_uri()` reads `LAKEHOUSE_URI`, raising `MissingLakehouseURIError` if it's unset. `storage_options()` returns `None` for a plain path, or the S3-compatible options `deltalake` needs for a non-AWS, plain-HTTP endpoint like SeaweedFS when it starts with `s3://`. `table_uri(name)` builds `<LAKEHOUSE_URI>/bronze/<name>` |
| [`lakehouse/bronze.py`](../../lakehouse/bronze.py) | `is_ingested(user_id, file_sha256)`: true if that file is already recorded for that user. `write_statement(statement, file_sha256)`: appends the statement's transactions to `bronze/transactions`, a summary row to `bronze/statements`, and a record to `bronze/ingested_files` — transactions and statements always append, so the caller checks `is_ingested()` first (see [CLI](cli.md)'s `pfp ingest`); the `ingested_files` record is written only when that sha256 isn't registered yet. `replace_statement(statement, file_sha256)` and `transactions_for_file(user_id, file_sha256)`: the backfill pair, below |
| [`ingestion/organizer.py`](../../ingestion/organizer.py)'s `ArchivedItem` | Carries the already-parsed `Statement` and its `sha256` (T14 extension) so `pfp ingest` writes to bronze without re-opening, re-decrypting or re-parsing a file `organize()` already handled |

## Replacing a file's rows (T14c)

`replace_statement(statement, file_sha256)` is what [`pfp backfill`](cli.md) calls once it has
re-parsed an already-archived statement: it deletes that file's rows from `bronze/transactions`
(`source_file_sha256`) and `bronze/statements` (`file_sha256`) with `DeltaTable.delete()`, then
writes the fresh parse through `write_statement()`. Three things about it are deliberate, and
[ADR 0010](../decisions/0010-bronze-backfill-replaces-not-versions.md) has the full reasoning:

- **The delete is scoped by `user_id` as well as the sha256.** Two users can hold the identical
  PDF (ADR 0009 files a joint account as one copy per user) and would share one `file_sha256`,
  so an unscoped delete would take the other user's rows with it. `user_id` is also the
  partition column, so the rewrite only ever touches that user's files. Covered by its own test.
- **`ingested_files` is untouched, `ingested_at` included** — the file's bytes never changed,
  only this parser's reading of them, so its "first ingested at" record stays true. The
  replacement `transactions`/`statements` rows do get a fresh `ingested_at`, which is what tells
  a backfilled row from an originally ingested one.
- **It's a thin wrapper, not a `replace=True` flag** inside `write_statement()`: the only
  difference from an ingest is the two deletes in front.

`transactions_for_file(user_id, file_sha256)` reads back what bronze currently holds for one
file as sorted `(date, description, amount)` tuples. It exists for `pfp backfill --dry-run`'s
comparison only; none of it is ever printed — the CLI reports counts and an unchanged/differs
verdict, never a value (ADR 0004).

Neither the delete nor the write is atomic with the other (delta-rs has no cross-table
transaction), so a crash mid-replace can leave a file with rows missing; re-running
`pfp backfill` fixes it, since the archived PDF is what the rows are derived from. Delta's log
keeps the previous rows readable by time travel (`DeltaTable(uri, version=n)`) until a `VACUUM`.

## account_kind (T18a)

`bronze/statements`' pyarrow schema carries `account_kind` (`"asset"`/`"liability"`) alongside
`opening_balance`/`closing_balance`, following the same fixed-schema pattern; `bronze/transactions`
deliberately does not — it has no balance/kind concept at all, and `account_kind` is a
Statement-level fact, not a per-transaction one. `dbt/models/silver/transactions.sql` joins it
back onto each transaction from `bronze.statements`, rather than it being duplicated into every
transaction row bronze-side. Full reasoning, including why the join key is `account_id` alone
(deduplicated), in [ADR 0014](../decisions/0014-account-kind-asset-or-liability.md).

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
uv run pfp backfill --user piero --dry-run   # what re-parsing the archive would change
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
- [ADR 0010: A backfill replaces a file's rows](../decisions/0010-bronze-backfill-replaces-not-versions.md) —
  why `replace_statement()` deletes instead of versioning.
- [ADR 0014: Account kind (asset/liability)](../decisions/0014-account-kind-asset-or-liability.md) —
  `account_kind` on `bronze/statements`, and why not on `bronze/transactions`.
- [CLI](cli.md) — `pfp ingest` and `pfp backfill`, the only callers of `write_statement()`,
  `is_ingested()`, `replace_statement()` and `transactions_for_file()`.
- [Inbox organizer](inbox-organizer.md) — produces the `ArchivedItem`s `pfp ingest` writes.
- [dbt silver](dbt-silver.md) — reads these Delta tables through `delta_scan()`; also where
  browsing bronze in DBeaver is documented, since it's the same on-disk DuckDB file dbt builds.
- [Phase 1](../phases/phase-1.md)
