"""De-risking test for T16: DuckDB reading bronze's Delta tables off local S3.

`tasks/plan.md`'s risk log flags "DuckDB reading Delta on local S3 (endpoint,
path-style, SSL)" as a medium risk to be checked "at the start of T16, before
modeling", and ADR 0002 says the same. This is that check, as a test rather than
a throwaway script, so the risky path stays proven as versions move.

Deselected by default, exactly like `tests/test_bronze_integration.py` (T14):
needs SeaweedFS running (`make poc-up`, T13) with `.env`'s values exported into
the shell (`set -a && source .env && set +a`). Run with `pytest -m integration`.

The `CREATE SECRET` shape below is what DuckDB documents for a non-AWS,
plain-HTTP S3 endpoint, and it is the same shape `dbt/profiles.yml` declares
through dbt-duckdb's `secrets:` block:
https://duckdb.org/docs/stable/core_extensions/httpfs/s3api
https://duckdb.org/docs/stable/core_extensions/delta
"""

import hashlib
import os
import uuid
from datetime import date
from decimal import Decimal

import duckdb
import pytest

from ingestion.schema import Statement, Transaction
from lakehouse import bronze
from lakehouse.storage import storage_options, table_uri

pytestmark = pytest.mark.integration

_REQUIRED_ENV = (
    "LAKEHOUSE_URI",
    "AWS_ENDPOINT_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)


def _skip_reason() -> str | None:
    if not os.environ.get("LAKEHOUSE_URI", "").startswith("s3://"):
        return (
            "LAKEHOUSE_URI must be an s3://... URI for this test; "
            "export .env's values first (see this file's docstring)."
        )
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        return f"missing env var(s): {', '.join(missing)} (see this file's docstring)"
    return None


def s3_secret_sql(name: str = "pfp_lake") -> str:
    """`CREATE SECRET ... TYPE s3 ... PROVIDER config` for the configured endpoint.

    `ENDPOINT` takes `host:port` with no scheme, so the scheme is stripped and
    also decides `USE_SSL`: SeaweedFS serves plain HTTP. `URL_STYLE 'path'`
    matches the same path-style addressing `lakehouse.storage.storage_options()`
    asks delta-rs for (`aws_virtual_hosted_style_request=false`, ADR 0006).
    """
    endpoint = os.environ["AWS_ENDPOINT_URL"]
    host = endpoint.split("://", 1)[-1].rstrip("/")
    use_ssl = "true" if endpoint.startswith("https://") else "false"
    return f"""
        CREATE OR REPLACE SECRET {name} (
            TYPE s3,
            PROVIDER config,
            KEY_ID '{os.environ["AWS_ACCESS_KEY_ID"]}',
            SECRET '{os.environ["AWS_SECRET_ACCESS_KEY"]}',
            REGION '{os.environ.get("AWS_REGION", "us-east-1")}',
            ENDPOINT '{host}',
            URL_STYLE 'path',
            USE_SSL {use_ssl}
        )
    """


@pytest.fixture
def user_id() -> str:
    return f"delta-scan-test-{uuid.uuid4().hex[:12]}"


def test_duckdb_delta_scan_reads_bronze_from_local_s3(user_id: str) -> None:
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
        transactions=[
            Transaction(
                user_id=user_id,
                bank="BCP",
                account_id=account_id,
                account_last4="9999",
                date=date(2026, 1, 15),
                description="DELTA SCAN TEST MOVEMENT",
                amount=Decimal("-25.50"),
                currency="PEN",
                source_file_sha256=file_sha256,
            )
        ],
    )

    try:
        bronze.write_statement(statement, file_sha256)

        with duckdb.connect() as connection:
            connection.execute("INSTALL httpfs; LOAD httpfs;")
            connection.execute("INSTALL delta; LOAD delta;")
            connection.execute(s3_secret_sql())
            rows = connection.execute(
                f"""
                SELECT date, description, amount, currency
                FROM delta_scan('{table_uri("transactions")}')
                WHERE user_id = ?
                """,
                [user_id],
            ).fetchall()

        assert rows == [
            (date(2026, 1, 15), "DELTA SCAN TEST MOVEMENT", Decimal("-25.50"), "PEN")
        ]
    finally:
        options = storage_options()
        for name in ("transactions", "statements", "ingested_files"):
            uri = table_uri(name)
            if DeltaTable.is_deltatable(uri, storage_options=options):
                DeltaTable(uri, storage_options=options).delete(
                    predicate=f"user_id = '{user_id}'"
                )
