"""The Superset virtual dataset behind the dynamic goal (T65, ADR 0048): the typed
native-filter values reach SQL only as numbers. Rendering only, no database; the numbers
it produces are `tests/test_dbt_goal_dynamic_integration.py`'s."""

import re

import pytest

from tests.goal_dynamic_sql import SQL_FILE, render

PARAMETERS = ("goal_amount_usd", "usd_to_pen", "emergency_months", "horizon_months")


def _defaults(sql: str, column: str) -> str:
    [line] = re.findall(rf"^\s*(.*) as {column},?$", sql, flags=re.MULTILINE)
    return line


def test_no_filter_leaves_every_parameter_to_its_default() -> None:
    sql = render()

    assert "null" in _defaults(sql, "goal_amount_usd")
    assert "coalesce" in _defaults(sql, "goal_amount_usd")
    assert "plan.goal_amount" in _defaults(sql, "goal_amount_usd")
    assert "plan.usd_to_pen" in _defaults(sql, "usd_to_pen")
    assert "plan.emergency_months" in _defaults(sql, "emergency_months")


def test_a_typed_number_becomes_a_numeric_literal() -> None:
    sql = render({"goal_amount_usd": ["25,000.50"], "usd_to_pen": ["3.8"]})

    assert "25000.5" in _defaults(sql, "goal_amount_usd")
    assert "3.8" in _defaults(sql, "usd_to_pen")


@pytest.mark.parametrize(
    "typed",
    [
        "1; drop table gold.rpt_goal_plan",
        "1 or 1=1",
        "'",
        "-5",
        "1e9",
        "NaN",
        "1.2.3",
        "9" * 30,
        "",
    ],
)
def test_anything_that_is_not_a_plain_number_falls_back_to_the_default(
    typed: str,
) -> None:
    sql = render({column: [typed] for column in PARAMETERS})

    for column in PARAMETERS:
        assert "null" in _defaults(sql, column)
    assert len(typed) < 3 or typed not in sql


def test_the_dataset_carries_user_id_and_the_four_filter_columns() -> None:
    sql = render()

    assert re.search(r"\buser_id\b", sql)
    for column in PARAMETERS:
        assert re.search(rf"\bas {column}\b", sql)


def test_it_reads_only_gold_tables() -> None:
    sources = set(re.findall(r"\b(?:from|join)\s+([a-z_]+\.[a-z_]+)", render()))

    assert sources
    assert {s.split(".")[0] for s in sources} == {"gold"}
    assert SQL_FILE.exists()
