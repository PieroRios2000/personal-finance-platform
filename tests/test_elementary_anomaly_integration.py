"""Elementary's row-count anomaly test on `silver.transactions` (T22, ADR 0022).

Reuses `tests/test_dbt_silver_integration.py`'s own `_dbt_build()` runner and
lake-wiping logic (`_skip_reason`/`_wipe_test_lake`, plain functions, not the
`lake` fixture object itself -- see `lake` below), the same "seed bronze
directly, run `dbt build`, check what comes out" pattern T16/T18a/T18b/T20/T23
already established, just against Elementary's own `elementary.volume_anomalies`
test (`dbt/models/silver/schema.yml`).

`lake` is redefined here rather than imported, for the same reason every other
`test_dbt_*_integration.py` file's own docstring gives: a fixture used across
files still has to appear under that exact parameter name for pytest's
dependency injection to find it, and importing a fixture object under the name
a test signature must also use trips ruff's F811 ("redefinition") on every
test that takes it.

Both scenarios below write one bank account's daily statements: 10 steady
"training" days (`_BASELINE_DAILY_COUNTS`, 4-6 transactions/day) immediately
followed by one "detection" day. The normal scenario's detection day stays in
that same 4-6 range; the broken scenario's detection day spikes to 40 --
`elementary.volume_anomalies`' own row-count anomaly detection (severity
`warn`, `min_training_set_size: 5`) is built to catch exactly this. The
detection day is dated *yesterday*, never *today*: Elementary excludes the
current, not-yet-elapsed calendar day from anomaly detection entirely
(confirmed empirically -- a spike seeded on `date.today()` never fires,
seeded on `date.today() - 1 day` reliably does), so a bucket for "today" is
never even evaluated.

Deselected by default, like the rest of the dbt integration suite: needs
SeaweedFS running (`make poc-up`, T13) with `.env` exported into the shell.
Run with `pytest -m integration`.
"""

import hashlib
import os
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ingestion.schema import Statement, Transaction
from lakehouse import bronze
from tests.test_dbt_silver_integration import (
    _TEST_LAKE_SUFFIX,
    _USER_ID,
    _dbt_build,
    _skip_reason,
    _wipe_test_lake,
)

pytestmark = pytest.mark.integration

_TEST_NAME = "elementary_volume_anomalies_silver_transactions"
_BANK = "BCP"
_LAST4 = "9999"
# 10 steady training days, small day-to-day variation (mean 5, stddev ~0.7)
# so the anomaly test's z-score-style scoring has real spread to compare
# against -- an exactly-flat baseline (stddev 0) would make *any* deviation
# read as an anomaly, which would prove nothing about the spike specifically.
_BASELINE_DAILY_COUNTS = [4, 5, 6, 5, 4, 6, 5, 4, 5, 6]
_NORMAL_DETECTION_DAY_COUNT = 5
_BROKEN_DETECTION_DAY_COUNT = 40


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


def _seed_daily_statements(*, scenario: str, detection_day_count: int) -> None:
    """One BCP checking account, one statement per day: 10 steady training
    days ending yesterday - 1, then one detection day (yesterday) with
    `detection_day_count` transactions. Each day's `opening_balance` chains
    from the previous day's `closing_balance`, so `assert_statement_continuity`
    (every dbt build already runs it) stays green throughout."""
    account_id = hashlib.sha256(f"t22-elementary-{scenario}".encode()).hexdigest()
    today = date.today()
    training_days = [
        today - timedelta(days=offset)
        for offset in range(len(_BASELINE_DAILY_COUNTS) + 1, 1, -1)
    ]
    detection_day = today - timedelta(days=1)
    days = [*training_days, detection_day]
    counts = [*_BASELINE_DAILY_COUNTS, detection_day_count]

    opening_balance = Decimal("1000.00")
    for day, count in zip(days, counts, strict=True):
        amounts = [Decimal("-1.00") for _ in range(count)]
        file_sha256 = hashlib.sha256(
            f"t22-elementary-{scenario}-{day}".encode()
        ).hexdigest()
        transactions = [
            Transaction(
                user_id=_USER_ID,
                bank=_BANK,
                account_id=account_id,
                account_last4=_LAST4,
                date=day,
                description=f"t22 elementary fixture movement {index}",
                amount=amount,
                currency="PEN",
                source_file_sha256=file_sha256,
            )
            for index, amount in enumerate(amounts)
        ]
        closing_balance = opening_balance + sum(amounts, start=Decimal("0"))
        statement = Statement(
            user_id=_USER_ID,
            bank=_BANK,
            account_id=account_id,
            account_last4=_LAST4,
            period_start=day,
            period_end=day,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            account_kind="asset",
            currency="PEN",
            transactions=transactions,
        )
        bronze.write_statement(statement, file_sha256)
        opening_balance = closing_balance


def _elementary_test_status(tmp_path: Path) -> str:
    """The anomaly test's own recorded status ('pass' or 'warn') straight out
    of Elementary's `elementary_test_results` table -- a stronger proof than
    parsing `dbt build`'s own console text, since it comes from the same
    table `edr report` (criterion 3) reads to render its report."""
    import duckdb

    with duckdb.connect(str(tmp_path / "pfp.duckdb"), read_only=True) as connection:
        row = connection.execute(
            "select status from elementary.elementary_test_results "
            "where test_name = ? order by detected_at desc limit 1",
            [_TEST_NAME],
        ).fetchone()
    assert row is not None, "elementary_test_results has no row for the anomaly test"
    return str(row[0])


def test_a_normal_day_does_not_fire_the_anomaly_test(lake: str, tmp_path: Path) -> None:
    _seed_daily_statements(
        scenario="normal", detection_day_count=_NORMAL_DETECTION_DAY_COUNT
    )

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout
    assert f"PASS {_TEST_NAME}" in result.stdout, result.stdout
    assert _elementary_test_status(tmp_path) == "pass"


def test_a_sudden_row_count_spike_fires_the_anomaly_test(
    lake: str, tmp_path: Path
) -> None:
    _seed_daily_statements(
        scenario="broken", detection_day_count=_BROKEN_DETECTION_DAY_COUNT
    )

    result = _dbt_build(tmp_path)

    # WARN, not ERROR: `config: {severity: warn}` in schema.yml (ADR 0022's
    # own warn-mode scoping) -- a real anomaly is surfaced, but `dbt build`'s
    # own exit code stays 0 so it doesn't yet block anything downstream.
    assert result.returncode == 0, result.stdout
    assert f"WARN 1 {_TEST_NAME}" in result.stdout, result.stdout
    assert _elementary_test_status(tmp_path) == "warn"


def _row_count(connection: Any, relation: str) -> int:
    row = connection.execute(f"select count(*) from {relation}").fetchone()
    assert row is not None
    return int(row[0])


def test_elementarys_own_models_build_alongside_silver_and_gold(
    lake: str, tmp_path: Path
) -> None:
    """T22's first acceptance criterion, checked directly: Elementary's own
    metadata/monitoring models land in the same `dbt build` as silver and
    gold, not a separate invocation."""
    _seed_daily_statements(
        scenario="models-build", detection_day_count=_NORMAL_DETECTION_DAY_COUNT
    )

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    import duckdb

    with duckdb.connect(str(tmp_path / "pfp.duckdb"), read_only=True) as connection:
        elementary_row_count = _row_count(connection, "elementary.dbt_run_results")
        silver_row_count = _row_count(connection, "silver.transactions")
        gold_row_count = _row_count(connection, "gold.fact_transactions")

    assert elementary_row_count > 0
    assert silver_row_count > 0
    assert gold_row_count > 0
