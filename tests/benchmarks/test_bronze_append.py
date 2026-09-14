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
from itertools import count
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
        account_kind="asset",
        currency="PEN",
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
    """Every round writes into its own empty lake.

    Pointing every round at the *same* lake measures the Delta log growing
    rather than the write: pytest-benchmark picks its own round count, and on
    a GitHub runner the mean came out 40.97 ms over 57 rounds against 51.78 ms
    over 71 — +26%, on identical code, which the 20% gate duly reported as a
    regression. Redirecting `LAKEHOUSE_URI` costs microseconds against a
    ~40 ms write, and makes every round measure the same work.
    """
    statement = _statement()
    lakes = (tmp_path / f"lake-{index}" for index in count())

    def append_to_a_fresh_lake() -> None:
        monkeypatch.setenv("LAKEHOUSE_URI", str(next(lakes)))
        bronze.write_statement(statement, FILE_SHA256)

    benchmark(append_to_a_fresh_lake)

    assert bronze.is_ingested(USER_ID, FILE_SHA256) is True
