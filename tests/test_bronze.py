"""Tests for lakehouse.bronze: bronze's Delta tables (T14) and the backfill
replace path (T14c)."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ingestion.schema import Statement, Transaction
from lakehouse import bronze

VALID_ACCOUNT_ID = hashlib.sha256(b"bcp:bronze-tests").hexdigest()
VALID_SHA256 = hashlib.sha256(b"a synthetic statement").hexdigest()


@pytest.fixture(autouse=True)
def lakehouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A disk-backed lake for each test: LAKEHOUSE_URI unset means no S3
    storage_options get built (lakehouse.storage.storage_options() returns
    None for a plain path)."""
    lake = tmp_path / "lake"
    monkeypatch.setenv("LAKEHOUSE_URI", str(lake))
    return lake


def _statement(*, user_id: str = "piero", **overrides: Any) -> Statement:
    kwargs: dict[str, Any] = {
        "user_id": user_id,
        "bank": "BCP",
        "account_id": VALID_ACCOUNT_ID,
        "account_last4": "1234",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
        "opening_balance": Decimal("100.00"),
        "closing_balance": Decimal("74.50"),
        "account_kind": "asset",
        "transactions": [
            Transaction(
                user_id=user_id,
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="TEST MOVEMENT",
                amount=Decimal("-25.50"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            )
        ],
    }
    kwargs.update(overrides)
    return Statement(**kwargs)


def test_is_ingested_is_false_before_anything_is_written() -> None:
    assert bronze.is_ingested("piero", VALID_SHA256) is False


def test_write_statement_makes_is_ingested_true() -> None:
    bronze.write_statement(_statement(), VALID_SHA256)

    assert bronze.is_ingested("piero", VALID_SHA256) is True


def test_write_statement_is_scoped_to_the_user(lakehouse: Path) -> None:
    bronze.write_statement(_statement(user_id="piero"), VALID_SHA256)

    assert bronze.is_ingested("piero", VALID_SHA256) is True
    assert bronze.is_ingested("someone-else", VALID_SHA256) is False


def test_write_statement_adds_one_row_per_transaction(lakehouse: Path) -> None:
    from deltalake import DeltaTable

    statement = _statement(
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="ONE",
                amount=Decimal("-25.50"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 20),
                description="TWO",
                amount=Decimal("300.00"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
        ]
    )

    bronze.write_statement(statement, VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows == 2
    amounts = sorted(table.column("amount").to_pylist())
    assert amounts == [Decimal("-25.50"), Decimal("300.00")]


def test_write_statement_preserves_decimal_precision_across_different_batches(
    lakehouse: Path,
) -> None:
    """A real bug found while building this: pyarrow infers a decimal128
    precision from each batch's own values, and deltalake rejects an append
    whose inferred precision differs from the table's existing one
    (`SchemaMismatchError: Cannot cast field amount from Decimal128(8, 2) to
    Decimal128(4, 2)`, reproduced directly against deltalake 1.6.3 before this
    was fixed with a fixed, explicit pyarrow schema)."""
    from deltalake import DeltaTable

    small = _statement(
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="SMALL",
                amount=Decimal("-12.34"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            )
        ]
    )
    large_sha256 = hashlib.sha256(b"a second synthetic statement").hexdigest()
    large = _statement(
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 2, 15),
                description="LARGE",
                amount=Decimal("123456.78"),
                currency="PEN",
                source_file_sha256=large_sha256,
            )
        ]
    )

    bronze.write_statement(small, VALID_SHA256)
    bronze.write_statement(large, large_sha256)  # must not raise SchemaMismatchError

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows == 2


def test_write_statement_adds_one_row_to_bronze_statements(lakehouse: Path) -> None:
    from deltalake import DeltaTable

    bronze.write_statement(_statement(), VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert table.num_rows == 1
    row = table.to_pylist()[0]
    assert row["opening_balance"] == Decimal("100.00")
    assert row["closing_balance"] == Decimal("74.50")
    assert row["period_start"] == date(2026, 1, 1)


def test_write_statement_carries_account_kind_into_bronze_statements(
    lakehouse: Path,
) -> None:
    """T18a: account_kind lives on Statement, not Transaction (an account's
    kind doesn't vary per movement), so only bronze/statements needs it --
    bronze/transactions has no balance/kind concept at all."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(account_kind="liability"), VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert table.to_pylist()[0]["account_kind"] == "liability"

    transactions = DeltaTable(
        str(lakehouse / "bronze" / "transactions")
    ).to_pyarrow_table()
    assert "account_kind" not in transactions.column_names


def test_write_statement_never_stores_a_file_name(lakehouse: Path) -> None:
    """Only the sha256 identifies the source file (ADR 0009): nothing in bronze
    should carry the original inbox filename."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(), VALID_SHA256)

    for table_name in ("transactions", "statements", "ingested_files"):
        table = DeltaTable(str(lakehouse / "bronze" / table_name)).to_pyarrow_table()
        assert "file_name" not in table.column_names
        assert "path" not in table.column_names


def test_ingesting_twice_does_not_duplicate_rows_when_the_caller_checks_first(
    lakehouse: Path,
) -> None:
    """write_statement() itself always appends — it's the caller's job to check
    is_ingested() first (see ingestion.cli._run_ingest); this test proves the
    idempotency contract holds when that's respected."""
    from deltalake import DeltaTable

    statement = _statement()
    if not bronze.is_ingested("piero", VALID_SHA256):
        bronze.write_statement(statement, VALID_SHA256)
    if not bronze.is_ingested("piero", VALID_SHA256):
        bronze.write_statement(statement, VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows == 1


def test_replace_statement_removes_the_old_transaction_rows(lakehouse: Path) -> None:
    """A backfill (T14c) re-parses a file already in bronze: the rows the
    previous (buggy) parse wrote are gone, and only the fresh ones remain."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(), VALID_SHA256)

    corrected = _statement(
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="CORRECTED ONE",
                amount=Decimal("-10.00"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 16),
                description="CORRECTED TWO",
                amount=Decimal("-15.50"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
        ]
    )
    bronze.replace_statement(corrected, VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert sorted(table.column("description").to_pylist()) == [
        "CORRECTED ONE",
        "CORRECTED TWO",
    ]


def test_replace_statement_replaces_the_statements_row(lakehouse: Path) -> None:
    from deltalake import DeltaTable

    bronze.write_statement(_statement(closing_balance=Decimal("74.50")), VALID_SHA256)

    bronze.replace_statement(_statement(closing_balance=Decimal("80.00")), VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert table.num_rows == 1
    assert table.to_pylist()[0]["closing_balance"] == Decimal("80.00")


def test_replace_statement_writes_a_file_that_was_never_ingested(
    lakehouse: Path,
) -> None:
    """Nothing to delete (a fresh lake has no tables at all) is a normal case,
    not an error: the statement is just written."""
    from deltalake import DeltaTable

    bronze.replace_statement(_statement(), VALID_SHA256)

    assert bronze.is_ingested("piero", VALID_SHA256) is True
    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows == 1


def test_replace_statement_keeps_the_original_ingested_files_row(
    lakehouse: Path,
) -> None:
    """A backfill corrects a file's *interpretation*, not the fact that the file
    itself was ingested at some earlier moment: `ingested_files` keeps its one
    row, with the `ingested_at` it already had."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(), VALID_SHA256)
    uri = str(lakehouse / "bronze" / "ingested_files")
    before = DeltaTable(uri).to_pyarrow_table().to_pylist()

    bronze.replace_statement(_statement(), VALID_SHA256)

    after = DeltaTable(uri).to_pyarrow_table().to_pylist()
    assert len(after) == 1
    assert after == before


def test_replace_statement_only_touches_the_given_users_rows(
    lakehouse: Path,
) -> None:
    """The same PDF can legitimately belong to two users (ADR 0009: a joint
    account lands as two independent copies, one per user), and both copies
    share one sha256 — so the delete has to be scoped by `user_id`, exactly like
    `is_ingested()` already is."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(user_id="piero"), VALID_SHA256)
    bronze.write_statement(_statement(user_id="ana"), VALID_SHA256)

    bronze.replace_statement(_statement(user_id="piero"), VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert sorted(table.column("user_id").to_pylist()) == ["ana", "piero"]
    statements = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert sorted(statements.column("user_id").to_pylist()) == ["ana", "piero"]


def test_transactions_for_file_is_empty_on_a_fresh_lake() -> None:
    assert bronze.transactions_for_file("piero", VALID_SHA256) == []


def test_transactions_for_file_returns_only_that_files_rows(lakehouse: Path) -> None:
    """What `pfp backfill --dry-run` compares a fresh parse against (T14c):
    date, description and amount for one file, and nothing else's."""
    other_sha256 = hashlib.sha256(b"another statement").hexdigest()
    bronze.write_statement(_statement(), VALID_SHA256)
    bronze.write_statement(
        _statement(
            transactions=[
                Transaction(
                    user_id="piero",
                    bank="BCP",
                    account_id=VALID_ACCOUNT_ID,
                    account_last4="1234",
                    date=date(2026, 2, 15),
                    description="ANOTHER FILE'S MOVEMENT",
                    amount=Decimal("-1.00"),
                    currency="PEN",
                    source_file_sha256=other_sha256,
                )
            ]
        ),
        other_sha256,
    )

    assert bronze.transactions_for_file("piero", VALID_SHA256) == [
        (date(2026, 1, 15), "TEST MOVEMENT", Decimal("-25.50"))
    ]


def test_two_users_land_in_separate_partitions_and_are_independent(
    lakehouse: Path,
) -> None:
    """Verifies partitioning by user_id (T14's acceptance criteria): both users'
    data lands under a `user_id=<id>` directory, and deleting one partition's
    files on disk leaves the other user's data fully readable."""
    import shutil

    from deltalake import DeltaTable

    piero_sha = VALID_SHA256
    ana_sha = hashlib.sha256(b"ana's statement").hexdigest()
    bronze.write_statement(_statement(user_id="piero"), piero_sha)
    bronze.write_statement(_statement(user_id="ana"), ana_sha)

    table_path = lakehouse / "bronze" / "transactions"
    partition_dirs = sorted(p.name for p in table_path.glob("user_id=*"))
    assert partition_dirs == ["user_id=ana", "user_id=piero"]

    shutil.rmtree(table_path / "user_id=ana")

    remaining = DeltaTable(str(table_path)).to_pyarrow_table(
        partitions=[("user_id", "=", "piero")]
    )
    assert remaining.num_rows == 1
    assert remaining.column("user_id").to_pylist() == ["piero"]
