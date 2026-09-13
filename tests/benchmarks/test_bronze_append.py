"""Bronze append benchmark: one statement's write to Delta (T15).

Deselected from the normal test run (`benchmark` marker, see `pyproject.toml`'s
`addopts`) and run on its own by CI's `benchmarks` job, base vs PR on the same
runner (CONSTRAINTS.md's "Performance" rule).

The lake is a `tmp_path` directory, not S3 (ADR 0006): this measures the write
path itself — building the pyarrow batches and committing the three Delta
tables — without a container or the network in the middle of the number.
"""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from ingestion.schema import Statement, Transaction
from lakehouse import bronze

pytestmark = pytest.mark.benchmark

ACCOUNT_ID = hashlib.sha256(b"bcp:benchmarks").hexdigest()
FILE_SHA256 = hashlib.sha256(b"a synthetic benchmark statement").hexdigest()
USER_ID = "benchmark"
ROWS = 100


def _statement() -> Statement:
    return Statement(
        user_id=USER_ID,
        bank="BCP",
        account_id=ACCOUNT_ID,
        account_last4="1234",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1000.00") + ROWS * Decimal("1.50"),
        transactions=[
            Transaction(
                user_id=USER_ID,
                bank="BCP",
                account_id=ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 1 + index % 28),
                description=f"MOVIMIENTO FICTICIO {index:03d}",
                amount=Decimal("1.50"),
                currency="PEN",
                source_file_sha256=FILE_SHA256,
            )
            for index in range(ROWS)
        ],
    )


def test_append_a_statement_to_bronze(
    benchmark: BenchmarkFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAKEHOUSE_URI", str(tmp_path / "lake"))
    statement = _statement()

    benchmark(bronze.write_statement, statement, FILE_SHA256)

    assert bronze.is_ingested(USER_ID, FILE_SHA256) is True
