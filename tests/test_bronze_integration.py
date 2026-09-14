"""Integration test for lakehouse.bronze against real local S3 (T14).

Deselected by default (see pyproject.toml's addopts, same pattern as `real_pdf`).
Needs SeaweedFS running: `make poc-up` (T13), with `.env`'s S3 values exported into
the shell, e.g. `set -a && source .env && set +a`. Run with `pytest -m integration`.

Uses a random per-run user_id so parallel or repeated runs never collide, and
deletes every row it wrote afterwards (`DeltaTable.delete`,
https://delta-io.github.io/delta-rs/api/delta_table/#deltalake.DeltaTable.delete)
so the shared SeaweedFS volume doesn't grow unbounded across runs.
"""

import hashlib
import os
import uuid
from datetime import date
from decimal import Decimal

import pytest

from ingestion.schema import Statement, Transaction
from lakehouse import bronze
from lakehouse.storage import table_uri

pytestmark = pytest.mark.integration

_REQUIRED_ENV = (
    "LAKEHOUSE_URI",
    "AWS_ENDPOINT_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)


def _skip_reason() -> str | None:
    if os.environ.get("LAKEHOUSE_URI", "").startswith("s3://") is False:
        return (
            "LAKEHOUSE_URI must be an s3://... URI for this test; "
            "export .env's values first (see this file's docstring)."
        )
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        return f"missing env var(s): {', '.join(missing)} (see this file's docstring)"
    return None


@pytest.fixture
def user_id() -> str:
    return f"integration-test-{uuid.uuid4().hex[:12]}"


def test_write_statement_round_trips_through_real_s3(user_id: str) -> None:
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    from deltalake import DeltaTable

    account_id = hashlib.sha256(f"bcp:{user_id}".encode()).hexdigest()
    file_sha256 = hashlib.sha256(f"statement for {user_id}".encode()).hexdigest()
    statement = Statement(
        user_id=user_id,
        bank="BCP",
        account_id=account_id,
        account_last4="9999",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("74.50"),
        account_kind="asset",
        currency="PEN",
        transactions=[
            Transaction(
                user_id=user_id,
                bank="BCP",
                account_id=account_id,
                account_last4="9999",
                date=date(2026, 1, 15),
                description="INTEGRATION TEST MOVEMENT",
                amount=Decimal("-25.50"),
                currency="PEN",
                source_file_sha256=file_sha256,
            )
        ],
    )

    try:
        assert bronze.is_ingested(user_id, file_sha256) is False

        bronze.write_statement(statement, file_sha256)

        assert bronze.is_ingested(user_id, file_sha256) is True

        from lakehouse.storage import storage_options

        options = storage_options()
        transactions = DeltaTable(
            table_uri("transactions"), storage_options=options
        ).to_pyarrow_table(partitions=[("user_id", "=", user_id)])
        assert transactions.num_rows == 1
        assert transactions.column("amount").to_pylist() == [Decimal("-25.50")]
    finally:
        from lakehouse.storage import storage_options

        options = storage_options()
        for name in ("transactions", "statements", "ingested_files"):
            uri = table_uri(name)
            if DeltaTable.is_deltatable(uri, storage_options=options):
                DeltaTable(uri, storage_options=options).delete(
                    predicate=f"user_id = '{user_id}'"
                )
