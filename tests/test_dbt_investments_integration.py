"""gold.fct_investment_monthly: each fund's return per month (ADR 0028).

Seeds `bronze.investment_entries` directly, builds dbt and checks the numbers.
Deselected by default (needs SeaweedFS, like the rest of the dbt integration
suite). Run with `pytest -m integration`.
"""

import hashlib
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ingestion.schema import Currency, InvestmentEntry, InvestmentKind, InvestmentMonth
from lakehouse import bronze
from tests import pg_store
from tests.test_dbt_gold_integration import lake as _lake
from tests.test_dbt_silver_integration import _USER_ID, _dbt_build

pytestmark = pytest.mark.integration

_SELECT = "fct_investment_monthly+ investment_entries"
# Not the shared calendar and what hangs off it (`dim_date+`): it also reads
# silver.transactions, which these tests do not write.
_EXCLUDE = "dim_date+"


# The same wiped, per-worker test lake every dbt integration file uses.
lake = _lake


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
    with pg_store.connect() as connection:
        cursor = connection.execute(
            "select * from gold.fct_investment_monthly "
            "order by place, currency, month_start"
        )
        assert cursor.description is not None
        names = [column.name for column in cursor.description]
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

    result = _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE)
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

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
    february = _rows(tmp_path)[("Fondo A", "PEN", 2)]

    assert february["cumulative_net_contributed"] == Decimal("50.00")
    assert february["cumulative_gain"] == Decimal("4.00")


def test_a_month_without_a_valuation_uses_the_last_balance_and_says_so(
    lake: str, tmp_path: Path
) -> None:
    """Until the owner types month-end valuations, the last balance of the month
    is its closing balance: the return is shown, and `closing_basis` tells it
    apart from a month closed by a real valuation."""
    _seed_fund_a()

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
    rows = _rows(tmp_path)
    march = rows[("Fondo A", "PEN", 3)]

    assert march["has_valuation"] is False
    assert march["closing_basis"] == "last_movement"
    assert march["gain"] == Decimal("1.00")
    # 1 / (54 + 10 * (31 - 10) / 31)
    assert round(float(march["return_pct"]), 4) == 0.0165
    assert march["is_return_reliable"] is True
    assert rows[("Fondo A", "PEN", 1)]["closing_basis"] == "valuation"


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

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
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

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
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

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
    january = _rows(tmp_path)[("Fondo D", "PEN", 1)]

    assert january["opening_balance"] == Decimal("510.00")
    assert january["gain"] == Decimal("2.00")
    # 510 already there + 100 put in = 610 net contributed; 612 - 610 earned
    assert january["cumulative_net_contributed"] == Decimal("610.00")
    assert january["cumulative_gain"] == Decimal("2.00")


def test_a_lake_with_no_investments_still_builds_with_empty_tables(
    lake: str, tmp_path: Path
) -> None:
    """The bronze table only exists once an investments sheet has been loaded."""
    result = _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE)

    assert result.returncode == 0, result.stdout
    assert _rows(tmp_path) == {}


def test_a_trailing_slash_in_the_lake_uri_still_finds_the_table(
    lake: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _month(
        "Fondo E",
        2026,
        1,
        [(5, "aporte", "100", "100"), (31, "valorizacion", "0", "101")],
    )
    monkeypatch.setenv("LAKEHOUSE_URI", os.environ["LAKEHOUSE_URI"] + "/")

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0

    assert ("Fondo E", "PEN", 1) in _rows(tmp_path)


def test_a_flow_on_the_last_day_has_no_weight_and_a_zero_capital_has_no_return(
    lake: str, tmp_path: Path
) -> None:
    """Opening 0 and the only contribution on the last day: nothing was invested
    during the month, so there is no capital to earn a return on."""
    _month(
        "Fondo F",
        2026,
        1,
        [(31, "aporte", "100", "100"), (31, "valorizacion", "0", "100")],
    )

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
    january = _rows(tmp_path)[("Fondo F", "PEN", 1)]

    assert january["return_pct"] is None
    assert january["is_return_reliable"] is False


def test_a_valuation_followed_by_a_contribution_closes_at_the_last_movement(
    lake: str, tmp_path: Path
) -> None:
    """A valuation on day 3 followed by a contribution on day 10: the month
    closes at 'the balance after the last movement', not at a valuation. Being
    the fund's first month with a valuation as its first row, no return."""
    _month(
        "Fondo G",
        2026,
        1,
        [(3, "valorizacion", "0", "100"), (10, "aporte", "10", "112")],
    )

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
    january = _rows(tmp_path)[("Fondo G", "PEN", 1)]

    assert january["has_valuation"] is False
    assert january["closing_basis"] == "last_movement"
    assert january["return_pct"] is None


def test_same_day_rows_are_ordered_by_their_row_in_the_sheet(
    lake: str, tmp_path: Path
) -> None:
    """A contribution and a valuation on the same day: the later row is the
    closing one."""
    _month(
        "Fondo H",
        2026,
        1,
        [(31, "aporte", "10", "110"), (31, "valorizacion", "0", "111")],
    )
    _month(
        "Fondo I",
        2026,
        1,
        [(31, "valorizacion", "0", "111"), (31, "aporte", "10", "121")],
    )

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
    rows = _rows(tmp_path)

    assert rows[("Fondo H", "PEN", 1)]["closing_balance"] == Decimal("111.00")
    assert rows[("Fondo I", "PEN", 1)]["closing_balance"] == Decimal("121.00")


def test_a_first_month_with_only_a_valuation_is_not_a_return(
    lake: str, tmp_path: Path
) -> None:
    """No flow marks where the fund starts: gain 0 would read as a 0% month."""
    _month("Fondo J", 2026, 1, [(31, "valorizacion", "0", "500")])

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
    january = _rows(tmp_path)[("Fondo J", "PEN", 1)]

    assert january["is_return_reliable"] is False
    assert january["return_pct"] is None


def test_a_month_with_only_a_valuation_after_a_first_month_is_a_real_return(
    lake: str, tmp_path: Path
) -> None:
    _month(
        "Fondo K",
        2026,
        1,
        [(5, "aporte", "100", "100"), (31, "valorizacion", "0", "100")],
    )
    _month("Fondo K", 2026, 2, [(28, "valorizacion", "0", "103")])

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
    february = _rows(tmp_path)[("Fondo K", "PEN", 2)]

    assert february["gain"] == Decimal("3.00")
    assert round(float(february["return_pct"]), 4) == 0.03
    assert february["is_return_reliable"] is True


def test_a_return_after_a_missing_month_is_not_shown(lake: str, tmp_path: Path) -> None:
    _month(
        "Fondo L",
        2026,
        1,
        [(5, "aporte", "100", "100"), (31, "valorizacion", "0", "101")],
    )
    _month("Fondo L", 2026, 3, [(31, "valorizacion", "0", "103")])

    assert _dbt_build(tmp_path, select=_SELECT, exclude=_EXCLUDE).returncode == 0
    march = _rows(tmp_path)[("Fondo L", "PEN", 3)]

    assert march["return_pct"] is None
