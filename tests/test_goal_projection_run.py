"""`scripts/goal_projection.py`: reads the plan and the balances, projects the savings
goal from the forecast's own fits and hands the rows to
`lakehouse.bronze.replace_goal_projection` (T60, ADR 0048, spec 4.4). The projection
arithmetic is `tests/test_forecast_projection.py`'s job and the SQL is
`tests/test_dbt_goal_integration.py`'s. All names and amounts here are synthetic."""

from collections.abc import Mapping
from datetime import date
from typing import Any

import pytest

from forecasting import backtest
from forecasting.fixed_expenses import MonthlySpend
from forecasting.projection import Balances, Plan
from forecasting.series import build_series
from lakehouse import bronze
from scripts import goal_projection as gp

RUN = date(2026, 9, 1)
OPEN_MONTH = date(2026, 10, 1)
SHOP = "PLANTEDSHOP"
RATE = 4.0


def _months(count: int) -> list[date]:
    last = RUN.year * 12 + RUN.month - 1
    return [date((last - i) // 12, (last - i) % 12 + 1, 1) for i in range(count)][::-1]


def _spend() -> list[MonthlySpend]:
    return [MonthlySpend("BCP", SHOP, "PEN", "Food", m, 1000.0) for m in _months(24)]


def _plan(**fields: Any) -> tuple[Plan, str]:
    values: dict[str, Any] = {
        "goal_amount": 5100.0,
        "usd_to_pen": RATE,
        "fixed": {"PEN": 400.0},
    }
    values.update(fields)
    return Plan(**values), "Ripley"


@pytest.fixture
def written(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, date, dict[str, Any]]]:
    calls: list[tuple[str, date, dict[str, Any]]] = []

    def capture(user_id: str, run_month: date, rows: Mapping[str, Any]) -> None:
        calls.append((user_id, run_month, dict(rows)))

    monkeypatch.setattr(bronze, "replace_goal_projection", capture)
    monkeypatch.setattr(gp, "fetch_plan", lambda user_id: _plan())
    monkeypatch.setattr(
        gp,
        "fetch_balances",
        lambda user_id, run_month, account: Balances(
            emergency={"PEN": 2000.0},
            other_liquid={"PEN": 4000.0},
            risk={"USD": 3000.0},
        ),
    )
    monkeypatch.setattr(
        gp,
        "fetch_income",
        lambda user_id: {("PEN", m): 4000.0 for m in _months(24)},
    )
    monkeypatch.setattr(
        gp,
        "fetch_liquid",
        lambda user_id, run_month: {("PEN", m): 6000.0 for m in _months(24)},
    )
    return calls


def _run() -> None:
    spending = _spend()
    series = list(
        build_series(spending, first_open_month=OPEN_MONTH, excluded=set()).values()
    )
    gp.run("piero", RUN, backtest.fit_all(series), series, spending)


def test_the_goal_is_projected_in_dollars_from_the_forecast_and_the_balances(
    written: list[tuple[str, date, dict[str, Any]]],
) -> None:
    _run()

    [(user_id, run_month, rows)] = written
    assert (user_id, run_month) == ("piero", RUN)
    summary = {
        (r["scenario"], r["line"]): r["months_to_goal"] for r in rows["goal_summary"]
    }
    assert summary[("base", "liquid")] == 9
    assert summary[("base", "with_risk")] == 5
    fund = {r["scenario"]: r for r in rows["emergency_fund"]}
    assert fund["base"]["target"] == pytest.approx(6 * (100 + 250))
    assert fund["base"]["bucket"] == pytest.approx(500)
    assert len(rows["goal_projection"]) == 3 * 2 * 121


def test_the_pieces_behind_the_projection_are_written_for_the_dashboard(
    written: list[tuple[str, date, dict[str, Any]]],
) -> None:
    _run()

    rows = written[0][2]
    assert len(rows["goal_cashflow"]) == 3 * 120
    first = next(
        r
        for r in rows["goal_cashflow"]
        if (r["scenario"], r["month_index"]) == ("base", 1)
    )
    assert first["currency"] == "PEN"
    assert first["fixed"] == pytest.approx(400)
    held = {(r["bucket"], r["currency"]): r["amount"] for r in rows["goal_balances"]}
    assert held[("emergency", "PEN")] == pytest.approx(2000)
    assert held[("risk", "USD")] == pytest.approx(3000)
    assert held[("essential", "PEN")] == pytest.approx(400 + 1000)


def test_the_adjust_view_has_one_row_per_variable_category(
    written: list[tuple[str, date, dict[str, Any]]],
) -> None:
    _run()

    [headroom] = written[0][2]["goal_headroom"]
    assert headroom["category"] == "Food"
    assert headroom["currency"] == "PEN"
    assert headroom["forecast"] == pytest.approx(250)


def test_without_an_exchange_rate_it_says_why_and_clears_the_old_answer(
    written: list[tuple[str, date, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    monkeypatch.setattr(gp, "fetch_plan", lambda user_id: _plan(usd_to_pen=None))

    _run()

    assert written == [("piero", RUN, {})]
    assert "usd_to_pen" in capsys.readouterr().out


def test_without_a_plan_nothing_is_projected_and_the_old_answer_is_cleared(
    written: list[tuple[str, date, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    monkeypatch.setattr(gp, "fetch_plan", lambda user_id: None)

    _run()

    assert written == [("piero", RUN, {})]
    assert "no plan imported" in capsys.readouterr().out


def test_too_little_income_history_is_refused(
    written: list[tuple[str, date, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    monkeypatch.setattr(
        gp, "fetch_income", lambda user_id: {("PEN", m): 4000.0 for m in _months(3)}
    )

    _run()

    assert written == [("piero", RUN, {})]
    assert "income" in capsys.readouterr().out


def test_an_income_override_stands_in_for_the_history(
    written: list[tuple[str, date, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gp, "fetch_income", lambda user_id: {})
    monkeypatch.setattr(
        gp, "fetch_plan", lambda user_id: _plan(income_override={"PEN": 4000.0})
    )

    _run()

    assert written[0][2]["goal_summary"]


def test_the_console_shows_counts_only(
    written: list[tuple[str, date, dict[str, Any]]], capsys: Any
) -> None:
    _run()

    out = capsys.readouterr().out
    assert SHOP not in out and "Food" not in out
    assert "goal projection" in out
