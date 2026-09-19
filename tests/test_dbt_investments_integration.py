"""gold.fct_investment_monthly: each fund's return per month (ADR 0028).

Seeds `bronze.investment_entries` directly, builds dbt and checks the numbers.
Deselected by default (needs SeaweedFS, like the rest of the dbt integration
suite). Run with `pytest -m integration`.
"""

import hashlib
import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ingestion.schema import Currency, InvestmentEntry, InvestmentKind, InvestmentMonth
from lakehouse import bronze
from tests.test_dbt_silver_integration import (
    _TEST_LAKE_SUFFIX,
    _USER_ID,
    _dbt_build,
    _skip_reason,
    _wipe_test_lake,
)

pytestmark = pytest.mark.integration

_SELECT = "fct_investment_monthly+ investment_entries"


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


def _month(
    place: str,
    year: int,
    month: int,
    rows: list[tuple[int, InvestmentKind, str, str]],
    currency: Currency = "PEN",
) -> None:
    """One fund-month: `(day, kind, amount, balance)` rows."""
    key = hashlib.sha256(f"{place}|{currency}|{year}-{month}".encode()).hexdigest()
    bronze.replace_investment_month(
        InvestmentMonth(
            user_id=_USER_ID,
            place=place,
            currency=currency,
            year=year,
            month=month,
            month_key=key,
            entries=[
                InvestmentEntry(
                    date=date(year, month, day),
                    kind=kind,
                    amount=Decimal(amount),
                    balance=Decimal(balance),
                    detail=None,
                    position=position,
                )
                for position, (day, kind, amount, balance) in enumerate(rows, start=2)
            ],
        )
    )


def _rows(tmp_path: Path) -> dict[tuple[str, str, int], dict[str, Any]]:
    import duckdb

    with duckdb.connect(str(tmp_path / "pfp.duckdb"), read_only=True) as connection:
        cursor = connection.execute(
            "select * from gold.fct_investment_monthly "
            "order by place, currency, month_start"
        )
        names = [d[0] for d in cursor.description]
        return {
            (
                r[names.index("place")],
                r[names.index("currency")],
                r[names.index("month_start")].month,
            ): dict(zip(names, r, strict=True))
            for r in cursor.fetchall()
        }


def _seed_fund_a() -> None:
    _month(
        "Fondo A",
        2026,
        1,
        [(5, "aporte", "100", "100"), (31, "valorizacion", "0", "102")],
    )
    _month(
        "Fondo A",
        2026,
        2,
        [(10, "retiro", "50", "53"), (28, "valorizacion", "0", "54")],
    )
    _month("Fondo A", 2026, 3, [(10, "aporte", "10", "65")])


def test_a_months_return_is_the_gain_over_the_time_weighted_capital(
    lake: str, tmp_path: Path
) -> None:
    _seed_fund_a()

    result = _dbt_build(tmp_path, select=_SELECT)
    assert result.returncode == 0, result.stdout
    rows = _rows(tmp_path)

    january = rows[("Fondo A", "PEN", 1)]
    assert january["opening_balance"] == Decimal("0.00")
    assert january["contributions"] == Decimal("100.00")
    assert january["closing_balance"] == Decimal("102.00")
    assert january["gain"] == Decimal("2.00")
    # 2 / (0 + 100 * (31 - 5) / 31)
    assert round(float(january["return_pct"]), 4) == 0.0238

    february = rows[("Fondo A", "PEN", 2)]
    assert february["opening_balance"] == Decimal("102.00")
    assert february["withdrawals"] == Decimal("50.00")
    assert february["gain"] == Decimal("2.00")
    # 2 / (102 - 50 * (28 - 10) / 28)
    assert round(float(february["return_pct"]), 4) == 0.0286


def test_cumulative_figures_track_net_contributions_and_total_gain(
    lake: str, tmp_path: Path
) -> None:
    _seed_fund_a()

    assert _dbt_build(tmp_path, select=_SELECT).returncode == 0
    february = _rows(tmp_path)[("Fondo A", "PEN", 2)]

    assert february["cumulative_net_contributed"] == Decimal("50.00")
    assert february["cumulative_gain"] == Decimal("4.00")


def test_a_month_without_a_valuation_has_no_reliable_return(
    lake: str, tmp_path: Path
) -> None:
    _seed_fund_a()

    assert _dbt_build(tmp_path, select=_SELECT).returncode == 0
    march = _rows(tmp_path)[("Fondo A", "PEN", 3)]

    assert march["has_valuation"] is False
    assert march["return_pct"] is None
    assert march["is_return_reliable"] is False


def test_a_missing_month_makes_the_next_return_unreliable(
    lake: str, tmp_path: Path
) -> None:
    _month(
        "Fondo B",
        2026,
        1,
        [(5, "aporte", "100", "100"), (31, "valorizacion", "0", "101")],
    )
    _month("Fondo B", 2026, 3, [(31, "valorizacion", "0", "103")])

    assert _dbt_build(tmp_path, select=_SELECT).returncode == 0
    rows = _rows(tmp_path)

    assert rows[("Fondo B", "PEN", 1)]["is_return_reliable"] is True
    march = rows[("Fondo B", "PEN", 3)]
    assert march["months_since_previous"] == 2
    assert march["is_return_reliable"] is False


def test_currencies_and_funds_are_never_mixed(lake: str, tmp_path: Path) -> None:
    _month(
        "Fondo C",
        2026,
        1,
        [(5, "aporte", "100", "100"), (31, "valorizacion", "0", "101")],
    )
    _month(
        "Fondo C",
        2026,
        1,
        [(5, "aporte", "10", "10"), (31, "valorizacion", "0", "10.5")],
        currency="USD",
    )

    assert _dbt_build(tmp_path, select=_SELECT).returncode == 0
    rows = _rows(tmp_path)

    assert rows[("Fondo C", "PEN", 1)]["closing_balance"] == Decimal("101.00")
    assert rows[("Fondo C", "USD", 1)]["closing_balance"] == Decimal("10.50")


def test_the_first_months_opening_is_the_balance_before_the_first_movement(
    lake: str, tmp_path: Path
) -> None:
    """A fund already worth 500 when the records begin: the first row is an
    aporte of 100 leaving 610, so it opened at 510 (with 10 already earned)."""
    _month(
        "Fondo D",
        2026,
        1,
        [(5, "aporte", "100", "610"), (31, "valorizacion", "0", "612")],
    )

    assert _dbt_build(tmp_path, select=_SELECT).returncode == 0
    january = _rows(tmp_path)[("Fondo D", "PEN", 1)]

    assert january["opening_balance"] == Decimal("510.00")
    assert january["gain"] == Decimal("2.00")
