"""The emergency fund and the savings-goal projection, in dollars (T60, ADR 0048).

Pure functions over plain inputs, no I/O. This is the one place soles become dollars:
`amount / usd_to_pen`, the owner's constant rate. Without a positive rate it refuses
rather than guess one.

New savings fill the emergency gap first, then go to the goal. Two lines are always
computed: `liquid` (the goal counts liquid savings only) and `with_risk` (the
investments also count, held flat at their last valuation). Three scenarios (base,
cautious, optimistic) take the same percentile every month; they are scenarios, not a
confidence interval. A goal not reached within 120 months is `None`, never a number.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from forecasting.series import add_months

HORIZON_MONTHS = 120
SCENARIOS = ("base", "cautious", "optimistic")
LINES = ("liquid", "with_risk")
MIN_INCOME_MONTHS = 6
INCOME_MONTHS = 12
VARIABLE_MONTHS = 6
CHECK_MONTHS = 6
MISMATCH_SHARE = 0.25
LONG_TARGET_MONTHS = 24
REFERENCE_PERCENTILE = 25
_EPSILON = 1e-9

# Which end of the total-spending interval and which income percentile each scenario
# takes.
_SPEND_END = {"base": 1, "cautious": 2, "optimistic": 0}
_INCOME_PERCENTILE = {"base": 50, "cautious": 25, "optimistic": 75}


class ProjectionRefused(ValueError):
    """The inputs cannot support a projection; the message says why, with no amounts."""


@dataclass(frozen=True)
class Plan:
    goal_amount: float
    usd_to_pen: float | None
    emergency_months: int = 6
    emergency_basis: str = "all"
    target_date: date | None = None
    income_override: Mapping[str, float] = field(default_factory=dict)
    fixed: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Balances:
    emergency: Mapping[str, float]
    other_liquid: Mapping[str, float]
    risk: Mapping[str, float]


@dataclass(frozen=True)
class TotalSpend:
    """Variable spending of one currency: closed months (oldest first) and the
    (p10, p50, p90) of horizons 1 to 3; an end is `None` without an interval."""

    history: Sequence[float]
    future: Sequence[tuple[float | None, float, float | None]]


@dataclass(frozen=True)
class CategoryOutlook:
    category: str
    currency: str
    forecast: float
    last12: Sequence[float]


@dataclass(frozen=True)
class MonthFlow:
    month: date
    income: Mapping[str, float]
    spending: Mapping[str, float]
    liquid: Mapping[str, float]


@dataclass(frozen=True)
class Inputs:
    plan: Plan
    balances: Balances
    last_closed_month: date
    income: Mapping[str, Sequence[float]]
    spend: Mapping[str, TotalSpend]
    categories: Sequence[CategoryOutlook] = ()
    flows: Sequence[MonthFlow] = ()


@dataclass(frozen=True)
class PathPoint:
    scenario: str
    line: str
    month_index: int
    month: date
    emergency: float
    goal_progress: float


@dataclass(frozen=True)
class GoalSummary:
    scenario: str
    line: str
    months_to_goal: int | None
    reached_month: date | None
    required_monthly_saving: float | None
    projected_monthly_saving: float
    gap: float | None
    headroom_share_of_gap: float | None


@dataclass(frozen=True)
class EmergencyFund:
    scenario: str
    target: float
    bucket: float
    gap: float
    months_to_fill: int | None
    months_covered: float | None
    months_of_income: float | None
    savings_rate: float | None
    essential_over_income: bool
    target_over_two_years_income: bool
    balance_mismatch: bool | None
    mismatch_months: int
    months_checked: int
    avg_net_flow: float | None
    avg_balance_change: float | None


@dataclass(frozen=True)
class Headroom:
    category: str
    currency: str
    forecast: float
    reference: float
    headroom: float
    share: float | None


@dataclass(frozen=True)
class Projection:
    path: list[PathPoint]
    summary: list[GoalSummary]
    emergency: list[EmergencyFund]
    headroom: list[Headroom]


def _to_usd(currency: str, amount: float, rate: float) -> float:
    if currency == "USD":
        return amount
    if currency == "PEN":
        return amount / rate
    raise ValueError(f"no conversion for currency {currency!r}")


def _sum_usd(amounts: Mapping[str, float], rate: float) -> float:
    return sum(_to_usd(c, a, rate) for c, a in amounts.items())


def _income_usd(inputs: Inputs, rate: float, percentile: float) -> float:
    plan = inputs.plan
    total = 0.0
    for currency in set(inputs.income) | set(plan.income_override):
        if currency in plan.income_override:
            amount = plan.income_override[currency]
        else:
            history = inputs.income[currency][-INCOME_MONTHS:]
            amount = float(np.percentile(history, percentile)) if history else 0.0
        total += _to_usd(currency, amount, rate)
    return total


def _check_income(inputs: Inputs) -> None:
    open_currencies = [
        len(history)
        for currency, history in inputs.income.items()
        if currency not in inputs.plan.income_override
    ]
    if inputs.plan.income_override:
        return
    if not open_currencies or max(open_currencies) < MIN_INCOME_MONTHS:
        raise ProjectionRefused(
            f"income needs {MIN_INCOME_MONTHS} closed months of history "
            "(or an override in the Meta sheet)"
        )


def _variable_usd(inputs: Inputs, rate: float, end: int) -> list[float]:
    """The variable spending of horizons 1 to 3 in dollars; a missing interval end falls
    back to the point forecast."""
    out = []
    for step in range(3):
        total = 0.0
        for currency, spend in inputs.spend.items():
            row = spend.future[min(step, len(spend.future) - 1)]
            picked = row[end]
            value = row[1] if picked is None else picked
            total += _to_usd(currency, value, rate)
        out.append(total)
    return out


def _essential_monthly(inputs: Inputs, rate: float) -> float:
    fixed = _sum_usd(inputs.plan.fixed, rate)
    if inputs.plan.emergency_basis == "fixed_only":
        return fixed
    variable = sum(
        _to_usd(currency, float(np.median(spend.history[-VARIABLE_MONTHS:])), rate)
        for currency, spend in inputs.spend.items()
        if len(spend.history)
    )
    return fixed + variable


def _required_saving(
    inputs: Inputs, rate: float, target: float, counted: float
) -> float | None:
    """The flat monthly saving that reaches the goal by `target_date`, emergency gap
    first. `counted` is what the line already holds besides the emergency account."""
    target_date, last = inputs.plan.target_date, inputs.last_closed_month
    if target_date is None:
        return None
    months = (target_date.year - last.year) * 12 + target_date.month - last.month
    if months < 1:
        return None
    still_needed = inputs.plan.goal_amount - counted
    if still_needed <= 0:
        return 0.0
    emergency = _sum_usd(inputs.balances.emergency, rate)
    return max(0.0, (target + still_needed - emergency) / months)


def _cross_check(
    flows: Sequence[MonthFlow], rate: float
) -> tuple[bool | None, int, int, float | None, float | None]:
    recent = list(flows)[-(CHECK_MONTHS + 1) :]
    nets, changes, off = [], [], 0
    for before, after in zip(recent, recent[1:], strict=False):
        spending = _sum_usd(after.spending, rate)
        net = _sum_usd(after.income, rate) - spending
        change = _sum_usd(after.liquid, rate) - _sum_usd(before.liquid, rate)
        nets.append(net)
        changes.append(change)
        off += abs(net - change) > MISMATCH_SHARE * spending
    if not nets:
        return None, 0, 0, None, None
    return (
        off * 2 > len(nets),
        off,
        len(nets),
        float(np.mean(nets)),
        float(np.mean(changes)),
    )


def _headroom(inputs: Inputs, rate: float) -> list[Headroom]:
    rows = []
    for item in inputs.categories:
        forecast = _to_usd(item.currency, item.forecast, rate)
        reference = _to_usd(
            item.currency,
            float(np.percentile(item.last12, REFERENCE_PERCENTILE)),
            rate,
        )
        rows.append((item, forecast, reference, max(0.0, forecast - reference)))
    total = sum(row[3] for row in rows)
    return [
        Headroom(
            item.category,
            item.currency,
            forecast,
            reference,
            headroom,
            headroom / total if total > 0 else None,
        )
        for item, forecast, reference, headroom in rows
    ]


def _first_month(values: Sequence[bool]) -> int | None:
    return next((t for t, hit in enumerate(values) if hit), None)


def project(inputs: Inputs) -> Projection:
    rate = inputs.plan.usd_to_pen
    if rate is None or not rate > 0:
        raise ProjectionRefused("usd_to_pen is needed to add soles and dollars")
    _check_income(inputs)

    plan, balances, last = inputs.plan, inputs.balances, inputs.last_closed_month
    emergency0 = _sum_usd(balances.emergency, rate)
    other = _sum_usd(balances.other_liquid, rate)
    risk = _sum_usd(balances.risk, rate)
    essential = _essential_monthly(inputs, rate)
    target = plan.emergency_months * essential
    fixed = _sum_usd(plan.fixed, rate)
    headroom = _headroom(inputs, rate)
    total_headroom = sum(h.headroom for h in headroom)
    cross = _cross_check(inputs.flows, rate)
    counted = {"liquid": other, "with_risk": other + risk}
    required = {
        line: _required_saving(inputs, rate, target, held)
        for line, held in counted.items()
    }

    path: list[PathPoint] = []
    summary: list[GoalSummary] = []
    funds: list[EmergencyFund] = []
    for scenario in SCENARIOS:
        income = _income_usd(inputs, rate, _INCOME_PERCENTILE[scenario])
        variable = _variable_usd(inputs, rate, _SPEND_END[scenario])
        savings = [income - fixed - variable[min(t, 3) - 1] for t in range(1, 121)]
        projected = float(np.mean(savings[:3]))
        cumulative = np.concatenate(([0.0], np.cumsum(savings)))
        spare = emergency0 + cumulative - target
        emergency = np.clip(emergency0 + cumulative, 0.0, target)
        goal = {line: held + np.maximum(0.0, spare) for line, held in counted.items()}

        for line in LINES:
            for t in range(HORIZON_MONTHS + 1):
                path.append(
                    PathPoint(
                        scenario,
                        line,
                        t,
                        add_months(last, t),
                        float(emergency[t]),
                        float(goal[line][t]),
                    )
                )
            months = _first_month(
                [bool(v >= plan.goal_amount - _EPSILON) for v in goal[line]]
            )
            needed = required[line]
            gap = None if needed is None else max(0.0, needed - projected)
            summary.append(
                GoalSummary(
                    scenario,
                    line,
                    months,
                    None if months is None else add_months(last, months),
                    required[line],
                    projected,
                    gap,
                    total_headroom / gap if gap else None,
                )
            )

        fill = _first_month([bool(v >= -_EPSILON) for v in spare])
        funds.append(
            EmergencyFund(
                scenario=scenario,
                target=target,
                bucket=emergency0,
                gap=max(0.0, target - emergency0),
                months_to_fill=fill,
                months_covered=emergency0 / essential if essential > 0 else None,
                months_of_income=target / income if income > 0 else None,
                savings_rate=projected / income if income > 0 else None,
                essential_over_income=essential > income,
                target_over_two_years_income=target > LONG_TARGET_MONTHS * income,
                balance_mismatch=cross[0],
                mismatch_months=cross[1],
                months_checked=cross[2],
                avg_net_flow=cross[3],
                avg_balance_change=cross[4],
            )
        )
    return Projection(path, summary, funds, headroom)
