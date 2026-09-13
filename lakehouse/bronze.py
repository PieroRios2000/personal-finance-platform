"""Bronze layer: append-only Delta tables for transactions, statements and the
ingested-files registry (T14), partitioned by `user_id` (ADR 0009).

Money columns use a fixed, explicit `decimal128(18, 2)` pyarrow schema rather
than letting pyarrow infer one from each batch's own values. Inference is
per-batch: a first write of small amounts infers `decimal128(4, 2)`, and a
later append with a larger amount (its own batch inferring `decimal128(8, 2)`)
gets rejected by deltalake — `SchemaMismatchError: Cannot cast field amount
from Decimal128(8, 2) to Decimal128(4, 2)` — reproduced directly against
deltalake 1.6.3 while building this. A fixed schema on every write sidesteps
that entirely; 18 total digits comfortably covers any realistic amount.
"""

from datetime import UTC, datetime
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


def write_statement(statement: Statement, file_sha256: str) -> None:
    """Append `statement`'s transactions and summary to bronze, and record
    `file_sha256` as ingested for `statement.user_id`.

    Always appends — call `is_ingested()` first if the file might already be
    in bronze (see `ingestion.cli._run_ingest`, T14's actual idempotency
    check). The original file name is never stored anywhere here (ADR 0009);
    only its sha256 identifies it.

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
        "file_sha256": file_sha256,
        "ingested_at": ingested_at,
    }
    _append("statements", _STATEMENTS_SCHEMA, [statement_row])

    ingested_file_row = {
        "user_id": statement.user_id,
        "file_sha256": file_sha256,
        "ingested_at": ingested_at,
    }
    _append("ingested_files", _INGESTED_FILES_SCHEMA, [ingested_file_row])
