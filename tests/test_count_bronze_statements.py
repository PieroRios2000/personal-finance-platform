"""Tests for scripts.count_bronze_statements (T21).

`ephemeral-integration`'s idempotency proof (`.github/workflows/ci.yml`)
switched from grepping `dagster asset materialize`'s own stdout for the
bronze asset's report text to comparing this script's output before and
after a second pass: a multi-asset `dagster asset materialize --select '*'`
does not stream a step's own `context.log.info()` output to stdout the way a
single-asset selection does (confirmed by reproducing it directly, both with
the default multiprocess executor and with `--config-json` forcing
`in_process`), so reading the real data is the reliable check.

Disk-backed lake (`lakehouse.storage.storage_options`: a plain path means no
S3 `storage_options`), the same boundary `tests/test_dagster_bronze.py`'s own
tests use -- no live SeaweedFS needed.
"""

from pathlib import Path

import pytest
from scripts.count_bronze_statements import main


@pytest.fixture(autouse=True)
def lakehouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    lake = tmp_path / "lake"
    monkeypatch.setenv("LAKEHOUSE_URI", str(lake))
    return lake


def test_prints_zero_when_bronze_statements_does_not_exist_yet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main() == 0

    assert capsys.readouterr().out.strip() == "0"


def test_prints_the_real_row_count(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import date
    from decimal import Decimal

    from ingestion.schema import Statement, Transaction
    from lakehouse import bronze

    statement = Statement(
        user_id="ci",
        bank="BCP",
        account_id="a" * 64,
        account_last4="0000",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("80.00"),
        account_kind="asset",
        currency="PEN",
        transactions=[
            Transaction(
                user_id="ci",
                bank="BCP",
                account_id="a" * 64,
                account_last4="0000",
                date=date(2026, 1, 5),
                description="movement",
                amount=Decimal("-20.00"),
                currency="PEN",
                source_file_sha256="b" * 64,
            )
        ],
    )
    bronze.write_statement(statement, "b" * 64)

    assert main() == 0

    assert capsys.readouterr().out.strip() == "1"
