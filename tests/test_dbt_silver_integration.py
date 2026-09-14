"""The dbt silver project against real local S3, continuity included (T16).

Seeds synthetic statements into a prefix of the lake reserved for this test
(`<LAKEHOUSE_URI>/_t16_dbt_tests`, never the real `<LAKEHOUSE_URI>/bronze`), runs
`dbt build` against exactly that data, and checks what comes out. Pointing dbt at
its own prefix is what makes the assertions deterministic: the continuity test
spans every statement in the lake, so it could not be checked against a lake that
also holds real, partially archived periods — and no real value is ever read.

Deselected by default, like `tests/test_bronze_integration.py` (T14): needs
SeaweedFS running (`make poc-up`, T13) with `.env` exported into the shell
(`set -a && source .env && set +a`). Run with `pytest -m integration`.
"""

import hashlib
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion.schema import Statement, Transaction
from lakehouse.storage import storage_options, table_uri

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_LAKE_SUFFIX = "_t16_dbt_tests"
_BANK = "BCP"
_LAST4 = "9999"
_ACCOUNT_ID = hashlib.sha256(b"t16-dbt-tests-account").hexdigest()
_USER_ID = "t16-dbt-tests"

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


def _wipe_test_lake() -> None:
    """Empty the test prefix's bronze tables, so every run starts from nothing.

    Only ever touches a URI containing `_t16_dbt_tests`; the assert is there so a
    mistake in the fixture can't reach the real lake.
    """
    from deltalake import DeltaTable

    options = storage_options()
    for name in ("transactions", "statements", "ingested_files"):
        uri = table_uri(name)
        assert _TEST_LAKE_SUFFIX in uri
        if DeltaTable.is_deltatable(uri, storage_options=options):
            DeltaTable(uri, storage_options=options).delete()


@pytest.fixture
def lake() -> Iterator[str]:
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    uri = f"{os.environ['LAKEHOUSE_URI'].rstrip('/')}/{_TEST_LAKE_SUFFIX}"
    previous = os.environ["LAKEHOUSE_URI"]
    os.environ["LAKEHOUSE_URI"] = uri
    try:
        _wipe_test_lake()
        yield uri
        _wipe_test_lake()
    finally:
        os.environ["LAKEHOUSE_URI"] = previous


def _write(
    period_start: date,
    period_end: date,
    opening_balance: str,
    movement: str,
) -> None:
    """Write one synthetic statement to the test lake, reconciled by construction.

    A `movement` of zero means a period with no transactions at all, which is what
    a dormant month looks like; `Transaction` rejects a zero amount (ADR 0005).
    """
    from lakehouse import bronze

    file_sha256 = hashlib.sha256(
        f"{period_start}:{opening_balance}:{movement}".encode()
    ).hexdigest()
    amount = Decimal(movement)
    transactions = []
    if amount != 0:
        transactions.append(
            Transaction(
                user_id=_USER_ID,
                bank=_BANK,
                account_id=_ACCOUNT_ID,
                account_last4=_LAST4,
                date=period_start,
                description="  compra pos....visa  ",
                amount=amount,
                currency="PEN",
                source_file_sha256=file_sha256,
            )
        )
    statement = Statement(
        user_id=_USER_ID,
        bank=_BANK,
        account_id=_ACCOUNT_ID,
        account_last4=_LAST4,
        period_start=period_start,
        period_end=period_end,
        opening_balance=Decimal(opening_balance),
        closing_balance=Decimal(opening_balance) + amount,
        account_kind="asset",
        transactions=transactions,
    )
    bronze.write_statement(statement, file_sha256)


_JANUARY = (date(2026, 1, 1), date(2026, 1, 31), "1000.00", "-100.00")
_FEBRUARY = (date(2026, 2, 1), date(2026, 2, 28), "900.00", "50.00")
_MARCH = (date(2026, 3, 1), date(2026, 3, 31), "950.00", "-50.00")
# February with movements that net to zero: the account's balance is identical on
# either side of it, so losing this statement leaves no balance drift at all --
# only the missing month itself. This is what the continuity test's date half is
# for, and the only thing that catches it.
_FEBRUARY_NET_ZERO = (date(2026, 2, 1), date(2026, 2, 28), "900.00", "0.00")
_MARCH_AFTER_NET_ZERO = (date(2026, 3, 1), date(2026, 3, 31), "900.00", "-50.00")


def _dbt_build(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """`dbt build` against the seeded test lake, writing its artifacts to tmp_path."""
    environment = {**os.environ, "PFP_DUCKDB_PATH": str(tmp_path / "pfp.duckdb")}
    return subprocess.run(
        [
            str(Path(sys.executable).parent / "dbt"),
            "build",
            "--project-dir",
            "dbt",
            "--profiles-dir",
            "dbt",
            "--target-path",
            str(tmp_path / "target"),
            "--log-path",
            str(tmp_path / "logs"),
        ],
        cwd=_REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_dbt_build_is_green_on_contiguous_periods(lake: str, tmp_path: Path) -> None:
    for period in (_JANUARY, _FEBRUARY, _MARCH):
        _write(*period)

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "PASS=" in result.stdout


def test_silver_normalizes_the_description(lake: str, tmp_path: Path) -> None:
    _write(*_JANUARY)

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    import duckdb

    with duckdb.connect(str(tmp_path / "pfp.duckdb"), read_only=True) as connection:
        descriptions = connection.execute(
            "select description from silver.transactions"
        ).fetchall()
    assert descriptions == [("COMPRA POS VISA",)]


def test_silver_carries_account_kind_without_duplicating_rows(
    lake: str, tmp_path: Path
) -> None:
    """T18a: account_kind lives on bronze.statements, not bronze.transactions,
    and this one account gets three statement rows here (one per period) --
    exactly the shape that would fan a naive join out into duplicates. 3
    transactions written, 3 rows must come back, each "asset" (these are all
    BCP fixtures), never 9."""
    for period in (_JANUARY, _FEBRUARY, _MARCH):
        _write(*period)

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    import duckdb

    with duckdb.connect(str(tmp_path / "pfp.duckdb"), read_only=True) as connection:
        rows = connection.execute(
            "select account_kind from silver.transactions"
        ).fetchall()

    assert rows == [("asset",), ("asset",), ("asset",)]


def test_a_missing_month_fails_the_continuity_test(lake: str, tmp_path: Path) -> None:
    """The proof T16 asks for: a gap between two archived periods is an error."""
    _write(*_JANUARY)
    _write(*_MARCH)

    failed = _dbt_build(tmp_path)

    assert failed.returncode != 0, failed.stdout
    assert "assert_statement_continuity" in failed.stdout
    assert "FAIL 1" in failed.stdout

    _write(*_FEBRUARY)

    fixed = _dbt_build(tmp_path)

    assert fixed.returncode == 0, fixed.stdout


def test_a_missing_month_that_nets_to_zero_still_fails(
    lake: str, tmp_path: Path
) -> None:
    """No balance drift, so only the date half of the rule can catch this."""
    _write(*_JANUARY)
    _write(*_MARCH_AFTER_NET_ZERO)

    failed = _dbt_build(tmp_path)

    assert failed.returncode != 0, failed.stdout
    assert "assert_statement_continuity" in failed.stdout

    _write(*_FEBRUARY_NET_ZERO)

    fixed = _dbt_build(tmp_path)

    assert fixed.returncode == 0, fixed.stdout
