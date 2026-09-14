"""Bronze layer: Delta tables for transactions, statements and the
ingested-files registry (T14), partitioned by `user_id` (ADR 0009).

Writes are appends, with one exception: `replace_statement()` (T14c) first
deletes what a previous parse of the same file wrote, so `pfp backfill` can
correct historical rows in place after a parser bug is fixed (ADR 0010).

Money columns use a fixed, explicit `decimal128(18, 2)` pyarrow schema rather
than letting pyarrow infer one from each batch's own values. Inference is
per-batch: a first write of small amounts infers `decimal128(4, 2)`, and a
later append with a larger amount (its own batch inferring `decimal128(8, 2)`)
gets rejected by deltalake — `SchemaMismatchError: Cannot cast field amount
from Decimal128(8, 2) to Decimal128(4, 2)` — reproduced directly against
deltalake 1.6.3 while building this. A fixed schema on every write sidesteps
that entirely; 18 total digits comfortably covers any realistic amount.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from ingestion.schema import Statement
from lakehouse.storage import storage_options, table_uri

_MONEY = pa.decimal128(18, 2)

_TRANSACTIONS_SCHEMA = pa.schema(
    [
        ("user_id", pa.string()),
        ("bank", pa.string()),
        ("account_id", pa.string()),
        ("account_last4", pa.string()),
        ("date", pa.date32()),
        ("description", pa.string()),
        ("amount", _MONEY),
        ("currency", pa.string()),
        ("source_file_sha256", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="UTC")),
    ]
)

_STATEMENTS_SCHEMA = pa.schema(
    [
        ("user_id", pa.string()),
        ("bank", pa.string()),
        ("account_id", pa.string()),
        ("account_last4", pa.string()),
        ("period_start", pa.date32()),
        ("period_end", pa.date32()),
        ("opening_balance", _MONEY),
        ("closing_balance", _MONEY),
        ("declared_charges_total", _MONEY),
        ("declared_credits_total", _MONEY),
        ("account_kind", pa.string()),
        ("currency", pa.string()),
        ("file_sha256", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="UTC")),
    ]
)

_INGESTED_FILES_SCHEMA = pa.schema(
    [
        ("user_id", pa.string()),
        ("file_sha256", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="UTC")),
    ]
)


def _append(name: str, schema: pa.Schema, rows: list[dict[str, Any]]) -> None:
    write_deltalake(
        table_uri(name),
        pa.Table.from_pylist(rows, schema=schema),
        mode="append",
        partition_by=["user_id"],
        storage_options=storage_options(),
    )


def _sql_literal(value: str) -> str:
    """Quote `value` as a SQL string literal: `DeltaTable.delete()` takes a SQL
    where clause, not bound parameters, so the quoting is ours to get right."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _delete_file_rows(name: str, column: str, user_id: str, file_sha256: str) -> None:
    """Delete every row of `bronze/<name>` that belongs to `user_id` and whose
    `<column>` holds `file_sha256`.

    Scoped by `user_id` for the same reason `is_ingested()` is: two users can
    hold the identical PDF (ADR 0009 files a joint account as one copy per
    user), and they'd share one sha256 — replacing one user's parse must not
    delete the other's rows. It's also the partition column, so the delete only
    ever rewrites that user's files.

    A table that doesn't exist yet (a fresh lake) is nothing to delete, not an
    error — the same `is_deltatable()` guard `is_ingested()` uses.
    """
    uri = table_uri(name)
    options = storage_options()
    if not DeltaTable.is_deltatable(uri, storage_options=options):
        return
    DeltaTable(uri, storage_options=options).delete(
        predicate=(
            f"user_id = {_sql_literal(user_id)} "
            f"AND {column} = {_sql_literal(file_sha256)}"
        )
    )


def is_ingested(user_id: str, file_sha256: str) -> bool:
    """True if `file_sha256` is already recorded for `user_id` in
    `bronze/ingested_files` — the caller's cue to skip re-writing it."""
    uri = table_uri("ingested_files")
    options = storage_options()
    if not DeltaTable.is_deltatable(uri, storage_options=options):
        return False
    table = DeltaTable(uri, storage_options=options).to_pyarrow_table(
        partitions=[("user_id", "=", user_id)], columns=["file_sha256"]
    )
    return file_sha256 in table.column("file_sha256").to_pylist()


def transactions_for_file(
    user_id: str, file_sha256: str
) -> list[tuple[date, str, Decimal]]:
    """Every transaction bronze currently holds for one file, as sorted
    `(date, description, amount)` tuples.

    What `pfp backfill --dry-run` (T14c) compares a fresh parse against to say
    whether re-parsing that file would change anything. Nothing here is ever
    printed: the CLI only reports counts and a differs/unchanged verdict.
    """
    uri = table_uri("transactions")
    options = storage_options()
    if not DeltaTable.is_deltatable(uri, storage_options=options):
        return []
    table = DeltaTable(uri, storage_options=options).to_pyarrow_table(
        partitions=[("user_id", "=", user_id)],
        columns=["source_file_sha256", "date", "description", "amount"],
    )
    rows: list[tuple[date, str, Decimal]] = [
        (row["date"], row["description"], row["amount"])
        for row in table.to_pylist()
        if row["source_file_sha256"] == file_sha256
    ]
    return sorted(rows)


def write_statement(statement: Statement, file_sha256: str) -> None:
    """Append `statement`'s transactions and summary to bronze, and record
    `file_sha256` as ingested for `statement.user_id` if it isn't already.

    Transactions and the statement summary are always appended — call
    `is_ingested()` first if the file might already be in bronze (see
    `ingestion.cli._run_ingest`, T14's actual idempotency check), or
    `replace_statement()` to swap an earlier parse out (T14c). The
    `ingested_files` record is the one write that's conditional: that table
    answers "has this file been ingested at all", so a second row for a sha256
    it already holds would say nothing new — and it's what lets a backfill
    reuse this function without inventing a duplicate registry entry for a file
    whose bytes never changed. The original file name is never stored anywhere
    here (ADR 0009); only its sha256 identifies it.

    The three tables aren't written atomically (delta-rs has no cross-table
    transaction); `ingested_files` is written last on purpose. A crash between
    writes leaves `is_ingested()` still `False`, so a retry re-appends
    duplicate transaction/statement rows rather than the other way around
    (writing `ingested_files` first could leave `is_ingested()` `True` with the
    transactions silently missing). Duplicates are visible and fixable; a
    silent gap in someone's transactions isn't. Not a concern in practice
    today — Phase 1 is a single local writer — but the ordering is deliberate.
    """
    ingested_at = datetime.now(UTC)

    transaction_rows = [
        {
            "user_id": transaction.user_id,
            "bank": transaction.bank,
            "account_id": transaction.account_id,
            "account_last4": transaction.account_last4,
            "date": transaction.date,
            "description": transaction.description,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "source_file_sha256": transaction.source_file_sha256,
            "ingested_at": ingested_at,
        }
        for transaction in statement.transactions
    ]
    if transaction_rows:
        _append("transactions", _TRANSACTIONS_SCHEMA, transaction_rows)

    statement_row = {
        "user_id": statement.user_id,
        "bank": statement.bank,
        "account_id": statement.account_id,
        "account_last4": statement.account_last4,
        "period_start": statement.period_start,
        "period_end": statement.period_end,
        "opening_balance": statement.opening_balance,
        "closing_balance": statement.closing_balance,
        "declared_charges_total": statement.declared_charges_total,
        "declared_credits_total": statement.declared_credits_total,
        "account_kind": statement.account_kind,
        "currency": statement.currency,
        "file_sha256": file_sha256,
        "ingested_at": ingested_at,
    }
    _append("statements", _STATEMENTS_SCHEMA, [statement_row])

    if not is_ingested(statement.user_id, file_sha256):
        ingested_file_row = {
            "user_id": statement.user_id,
            "file_sha256": file_sha256,
            "ingested_at": ingested_at,
        }
        _append("ingested_files", _INGESTED_FILES_SCHEMA, [ingested_file_row])


def replace_statement(statement: Statement, file_sha256: str) -> None:
    """Replace whatever an earlier parse of `file_sha256` wrote with this one:
    delete that file's rows from `transactions` and `statements`, then write
    `statement` (T14c, ADR 0010 — replace, don't version).

    A thin wrapper on purpose, rather than a `replace=True` flag inside
    `write_statement()`: the only difference between ingesting a file and
    backfilling it is the two deletes in front, and a flag would put a branch
    in the middle of the write path that every caller then has to reason about.

    `ingested_files` is deliberately left alone. The file's bytes — and so its
    sha256 — haven't changed; only this parser's reading of them has, so its
    "first ingested at" record stays true (`write_statement()` won't add a
    second one). The `ingested_at` on the replacement `transactions`/
    `statements` rows *is* fresh, and is what tells a backfilled row from an
    originally ingested one.

    Not atomic across the two tables (delta-rs has no cross-table transaction,
    the same caveat `write_statement()` documents), and not atomic within one
    either: a crash between the delete and the write leaves that file with no
    rows in bronze. That's recoverable by re-running `pfp backfill` — the
    archived PDF is still the source of truth and nothing about it changed —
    which is why the archive, not bronze, is what must never be lost.
    """
    _delete_file_rows(
        "transactions", "source_file_sha256", statement.user_id, file_sha256
    )
    _delete_file_rows("statements", "file_sha256", statement.user_id, file_sha256)
    write_statement(statement, file_sha256)
