"""Project the savings goal and the emergency fund from the forecast (T60).

Called by `scripts.forecast` right after it writes the forecast (`make forecast`):
reads the owner's plan from silver and the balances, income and liquid-savings history
from gold in a read-only session, projects in dollars with `forecasting.projection` and
writes the four goal tables to bronze, replacing this user's whole projection (ADR 0048,
spec 4.4). When it cannot project (no plan, no exchange rate, too little income history)
it says why in words, with no amounts, and clears the old answer so the dashboard never
shows a stale one. Prints counts only."""

import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo

from forecasting import backtest
from forecasting.fixed_expenses import MonthlySpend
from forecasting.projection import (
    HORIZON_MONTHS,
    Balances,
    CategoryOutlook,
    Inputs,
    MonthFlow,
    Plan,
    Projection,
    ProjectionRefused,
    TotalSpend,
    project,
)
from forecasting.series import TOTAL, Series, add_months
from lakehouse import bronze
from scripts.pg_databases import conninfo

CHECK_MONTHS = 7
LAST12 = 12

Monthly = Mapping[tuple[str, date], float]


def _query(sql: str, params: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    read_only = make_conninfo(
        conninfo(os.environ["PFP_PG_DATABASE"]),
        options="-c default_transaction_read_only=on",
    )
    with psycopg.connect(read_only) as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def fetch_plan(user_id: str) -> tuple[Plan, str] | None:
    """The plan's goal settings and fixed monthly amounts, with the emergency account's
    name; None when no plan has been imported (silver is empty or not built yet)."""
    try:
        goals = _query(
            """
            select goal_amount, usd_to_pen, emergency_months, emergency_basis,
                emergency_account, target_date, income_pen_override, income_usd_override
            from silver.plan_goal where user_id = %(user)s
            """,
            {"user": user_id},
        )
        fixed = _query(
            """
            select currency, sum(expected_amount) from silver.plan_fixed_items
            where user_id = %(user)s and kind = 'fixed' group by currency
            """,
            {"user": user_id},
        )
    except psycopg.errors.UndefinedTable:
        return None
    if not goals:
        return None
    amount, rate, months, basis, account, target, pen, usd = goals[0]
    overrides = {"PEN": pen, "USD": usd}
    plan = Plan(
        goal_amount=float(amount),
        usd_to_pen=None if rate is None else float(rate),
        emergency_months=months,
        emergency_basis=basis,
        target_date=target,
        income_override={c: float(v) for c, v in overrides.items() if v is not None},
        fixed={str(c): float(v) for c, v in fixed if v is not None},
    )
    return plan, str(account)


def fetch_balances(user_id: str, run_month: date, account: str) -> Balances:
    """Emergency (the named account), other liquid (the rest of the asset accounts) and
    risk (the investments), per currency, at the last closed month."""
    params = {"user": user_id, "run": run_month, "bank": account}
    emergency = _query(
        """
        select currency, sum(closing_balance) from (
            select distinct on (account_id, currency)
                account_id, currency, closing_balance
            from gold.fct_account_balance_monthly
            where user_id = %(user)s and bank = %(bank)s and account_kind = 'asset'
                and month_start <= %(run)s
            order by account_id, currency, month_start desc
        ) as latest group by currency
        """,
        params,
    )
    capital = _query(
        """
        select currency, savings_balance, investments_balance from gold.rpt_capital
        where user_id = %(user)s and month_start = %(run)s
        """,
        params,
    )
    held = {str(c): float(v) for c, v in emergency}
    return Balances(
        emergency=held,
        other_liquid={str(c): float(s) - held.get(str(c), 0.0) for c, s, _i in capital},
        risk={str(c): float(i) for c, _s, i in capital},
    )


def fetch_income(user_id: str) -> Monthly:
    rows = _query(
        """
        select currency, date_trunc('month', date)::date, sum(amount)
        from gold.rpt_movements
        where user_id = %(user)s and flow_type = 'ingreso' and not is_internal_transfer
        group by 1, 2
        """,
        {"user": user_id},
    )
    return {(str(c), m): float(a) for c, m, a in rows}


def fetch_liquid(user_id: str, run_month: date) -> Monthly:
    rows = _query(
        """
        select currency, month_start, savings_balance from gold.rpt_capital
        where user_id = %(user)s and month_start <= %(run)s
        """,
        {"user": user_id, "run": run_month},
    )
    return {(str(c), m): float(b) for c, m, b in rows}


def _income_history(income: Monthly, run_month: date) -> dict[str, list[float]]:
    """Income per closed month from the first month a currency has any, zero-filled
    after it (a month without income is a real zero) to the last closed month."""
    first: dict[str, date] = {}
    for currency, month in income:
        first[currency] = min(first.get(currency, month), month)
    history = {}
    for currency, month in first.items():
        values = []
        while month <= run_month:
            values.append(income.get((currency, month), 0.0))
            month = add_months(month, 1)
        history[currency] = values
    return history


def _flows(
    run_month: date,
    income: Monthly,
    liquid: Monthly,
    spending: Sequence[MonthlySpend],
) -> list[MonthFlow]:
    spent: dict[tuple[str, date], float] = defaultdict(float)
    for row in spending:
        spent[(row.currency, row.month)] += row.amount
    flows = []
    for offset in range(CHECK_MONTHS - 1, -1, -1):
        month = add_months(run_month, -offset)
        balances = {c: v for (c, m), v in liquid.items() if m == month}
        if not balances:
            continue
        flows.append(
            MonthFlow(
                month,
                {c: v for (c, m), v in income.items() if m == month},
                {c: v for (c, m), v in spent.items() if m == month},
                balances,
            )
        )
    return flows


def _inputs(
    plan: Plan,
    balances: Balances,
    run_month: date,
    fits: Sequence[backtest.SeriesFit],
    series: Sequence[Series],
    spending: Sequence[MonthlySpend],
    income: Monthly,
    liquid: Monthly,
) -> Inputs:
    totals: dict[str, TotalSpend] = {}
    categories = []
    for fit, one in zip(fits, series, strict=True):
        if one.category == TOTAL:
            future = [(i.p10, i.p50, i.p90) for i in fit.future]
            totals[one.currency] = TotalSpend(list(one.values), future)
        else:
            categories.append(
                CategoryOutlook(
                    one.category,
                    one.currency,
                    fit.future[0].p50,
                    list(one.values[-LAST12:]),
                )
            )
    return Inputs(
        plan=plan,
        balances=balances,
        last_closed_month=run_month,
        income=_income_history(income, run_month),
        spend=totals,
        categories=categories,
        flows=_flows(run_month, income, liquid, spending),
    )


def _tables(projection: Projection) -> dict[str, list[dict[str, Any]]]:
    return {
        "goal_projection": [asdict(r) for r in projection.path],
        "goal_summary": [asdict(r) for r in projection.summary],
        "emergency_fund": [asdict(r) for r in projection.emergency],
        "goal_headroom": [asdict(r) for r in projection.headroom],
        "goal_cashflow": [asdict(r) for r in projection.cashflow],
        "goal_balances": [asdict(r) for r in projection.balances],
    }


def _reached(value: int | None) -> str:
    return f"in {value} months" if value is not None else f"not within {HORIZON_MONTHS}"


def run(
    user_id: str,
    run_month: date,
    fits: Sequence[backtest.SeriesFit],
    series: Sequence[Series],
    spending: Sequence[MonthlySpend],
) -> None:
    loaded = fetch_plan(user_id)
    if loaded is None:
        print("no plan imported: goal projection skipped (make import-plan)")
        bronze.replace_goal_projection(user_id, run_month, {})
        return
    plan, account = loaded
    try:
        projection = project(
            _inputs(
                plan,
                fetch_balances(user_id, run_month, account),
                run_month,
                fits,
                series,
                spending,
                fetch_income(user_id),
                fetch_liquid(user_id, run_month),
            )
        )
    except ProjectionRefused as refusal:
        print(f"goal projection skipped: {refusal}")
        bronze.replace_goal_projection(user_id, run_month, {})
        return
    bronze.replace_goal_projection(user_id, run_month, _tables(projection))
    reached = {
        r.line: r.months_to_goal for r in projection.summary if r.scenario == "base"
    }
    print(
        f"goal projection: {len(projection.summary)} scenario lines, "
        f"{len(projection.headroom)} categories in the adjust view written"
    )
    print(
        f"base case reaches the goal {_reached(reached['liquid'])} (liquid) and "
        f"{_reached(reached['with_risk'])} (with investments)"
    )
