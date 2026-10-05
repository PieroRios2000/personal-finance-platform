"""silver.plan_* and gold.rpt_fixed_expenses: the owner's plan against what was
really charged (T57, ADR 0048).

Seeds `bronze.statements` and the plan tables directly, builds dbt and checks the
numbers. Deselected by default (needs SeaweedFS and Postgres, like the rest of the dbt
integration suite). Run with `pytest -m integration`. All data is synthetic.
"""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ingestion.schema import Statement, Transaction
from lakehouse import bronze
from tests import pg_store
from tests.test_dbt_gold_integration import _month_bounds
from tests.test_dbt_gold_integration import lake as _lake
from tests.test_dbt_silver_integration import (
    _ACCOUNT_ID,
    _BANK,
    _LAST4,
    _USER_ID,
    _dbt_build,
)

pytestmark = pytest.mark.integration

lake = _lake


def _statement_for(
    months_ago: int, charges: dict[str, str], opening_balance: Decimal
) -> Decimal:
    """One reconciled statement for the month `months_ago` before this one, with one
    spending transaction per `description: amount` on its first day; returns the
    closing balance, which the next month opens with."""
    first, last = _month_bounds(months_ago)
    sha = hashlib.sha256(f"t57-plan-{months_ago}".encode()).hexdigest()
    transactions = [
        Transaction(
            user_id=_USER_ID,
            bank=_BANK,
            account_id=_ACCOUNT_ID,
            account_last4=_LAST4,
            date=first,
            description=description.lower(),
            amount=-Decimal(amount),
            currency="PEN",
            source_file_sha256=sha,
        )
        for description, amount in charges.items()
    ]
    closing = opening_balance + sum((t.amount for t in transactions), Decimal(0))
    bronze.write_statement(
        Statement(
            user_id=_USER_ID,
            bank=_BANK,
            account_id=_ACCOUNT_ID,
            account_last4=_LAST4,
            period_start=first,
            period_end=last,
            opening_balance=opening_balance,
            closing_balance=closing,
            account_kind="asset",
            currency="PEN",
            transactions=transactions,
        ),
        sha,
    )
    return closing


def _seed_spending() -> None:
    """Rent for six closed months (the last one 15 % above), a gym in two of them,
    a streaming service that the plan calls variable, and a big rent charge in the
    current, still open month that must not be counted."""
    charges = {
        6: {"planted rent": "1000", "planted stream": "30"},
        5: {"planted rent": "1000", "planted gym": "80", "planted stream": "30"},
        4: {"planted rent": "1000", "planted stream": "30"},
        3: {"planted rent": "1000", "planted gym": "80", "planted stream": "30"},
        2: {"planted rent": "1000", "planted stream": "30"},
        1: {"planted rent": "1150", "planted stream": "30"},
        0: {"planted rent": "5000"},
    }
    balance = Decimal("50000")
    for months_ago in range(6, -1, -1):
        balance = _statement_for(months_ago, charges[months_ago], balance)


def _item(description: str, kind: str, expected: float | None) -> bronze.PlanItemRow:
    return bronze.PlanItemRow(
        bank=_BANK,
        description=description,
        currency="PEN",
        category="Servicios",
        months_seen=6,
        typical_amount=expected,
        proposed_kind=kind,
        kind=kind,
        expected_amount=expected,
        note="",
    )


def _goal() -> bronze.PlanGoalRow:
    return bronze.PlanGoalRow(
        goal_amount=10000.0,
        usd_to_pen=3.75,
        emergency_months=6,
        emergency_basis="all",
        emergency_account="Ripley",
        target_date=date(2099, 12, 31),
        income_pen_override=None,
        income_usd_override=None,
    )


def _rows(relation: str) -> list[dict[str, Any]]:
    with pg_store.connect() as connection:
        cursor = connection.execute(f"select * from {relation} order by 1, 2, 3")
        assert cursor.description is not None
        names = [column.name for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def test_fixed_expenses_compare_the_plan_with_the_closed_months(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()
    bronze.replace_plan(
        _USER_ID,
        [
            _item("PLANTED RENT", "fixed", 1000.0),
            _item("PLANTED GYM", "fixed", 80.0),
            _item("PLANTED NEVER", "fixed", 40.0),
            _item("PLANTED STREAM", "variable", 30.0),
            _item("PLANTED ONE-OFF", "ignore", None),
        ],
        _goal(),
    )

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    rows = {row["description"]: row for row in _rows("gold.rpt_fixed_expenses")}
    assert set(rows) == {"PLANTED RENT", "PLANTED GYM", "PLANTED NEVER"}
    assert {row["user_id"] for row in rows.values()} == {_USER_ID}

    rent = rows["PLANTED RENT"]
    assert rent["expected_amount"] == Decimal("1000.00")
    assert rent["months_seen_last_6"] == 6
    assert rent["last_observed_month"] == _month_bounds(1)[0]
    assert rent["last_observed_amount"] == Decimal("1150.00")
    assert float(rent["deviation_pct"]) == pytest.approx(15.0)
    assert rent["status"] == "deviating"

    gym = rows["PLANTED GYM"]
    assert gym["months_seen_last_6"] == 2
    assert gym["last_observed_month"] == _month_bounds(3)[0]
    assert float(gym["deviation_pct"]) == pytest.approx(0.0)
    assert gym["status"] == "as_expected"

    never = rows["PLANTED NEVER"]
    assert never["months_seen_last_6"] == 0
    assert never["last_observed_month"] is None
    assert never["deviation_pct"] is None
    assert never["status"] == "not_seen"


def test_silver_plan_goal_keeps_the_dollar_goal_and_the_rate(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()
    bronze.replace_plan(_USER_ID, [_item("PLANTED RENT", "fixed", 1000.0)], _goal())

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    [goal] = _rows("silver.plan_goal")
    assert goal["user_id"] == _USER_ID
    assert goal["goal_amount"] == Decimal("10000.00")
    assert goal["goal_currency"] == "USD"
    assert goal["usd_to_pen"] == pytest.approx(3.75)
    assert goal["emergency_basis"] == "all"
    assert goal["target_date"] == date(2099, 12, 31)


def test_the_models_build_empty_before_any_plan_is_imported(
    lake: str, tmp_path: Path
) -> None:
    _seed_spending()

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _rows("gold.rpt_fixed_expenses") == []
    assert _rows("silver.plan_goal") == []
