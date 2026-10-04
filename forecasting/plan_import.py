"""What makes a plan workbook importable (T57, ADR 0048, spec 4.1).

A pure check over a `PlanFile`: every problem is listed at once, by sheet and row number
or field name, and never repeats a value the owner typed (a description or an amount is
his own data). The lake is not touched here; the caller passes what it needs to know
(today's date, the asset accounts the lake has).
"""

import math
from dataclasses import dataclass
from datetime import date, datetime

from forecasting.plan_file import KINDS, SHEET_ITEMS, SHEET_META, PlanFile, PlanItem

CURRENCIES = ("PEN", "USD")
EMERGENCY_BASES = ("all", "fixed_only")
MIN_EMERGENCY_MONTHS = 1
MAX_EMERGENCY_MONTHS = 24


@dataclass(frozen=True)
class Goal:
    goal_amount: float
    usd_to_pen: float
    emergency_months: int
    emergency_basis: str
    emergency_account: str
    target_date: date | None
    income_pen_override: float | None
    income_usd_override: float | None


def _number(value: object) -> float | None:
    """A finite number from a cell, or `None` if it is not one (text with a comma,
    words, a boolean, NaN or infinity)."""
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _positive(value: object) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _is_empty(value: object) -> bool:
    return value is None or str(value).strip() == ""


def _date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _item_problems(
    item: PlanItem, first_seen: dict[tuple[str, str, str], int]
) -> list[str]:
    where = f"{SHEET_ITEMS}:"
    problems: list[str] = []
    if not item.bank:
        problems.append(f"{where} bank in row {item.row} is empty")
    if item.currency not in CURRENCIES:
        problems.append(f"{where} currency in row {item.row} must be PEN or USD")
    if item.kind not in KINDS:
        problems.append(
            f"{where} kind in row {item.row} must be fixed, variable or ignore"
        )
    amount_given = item.expected_amount is not None
    if (amount_given or item.kind == "fixed") and _positive(
        item.expected_amount
    ) is None:
        problems.append(
            f"{where} expected_amount in row {item.row} must be a positive number"
        )
    earlier = first_seen.setdefault(item.key, item.row)
    if earlier != item.row:
        problems.append(
            f"{where} row {item.row} repeats the bank, description and currency "
            f"of row {earlier}"
        )
    return problems


def _optional_positive(
    meta: dict[str, object], field: str, problems: list[str]
) -> float | None:
    value = meta.get(field)
    if _is_empty(value):
        return None
    number = _positive(value)
    if number is None:
        problems.append(f"{SHEET_META}: {field} must be a positive number")
    return number


def _required_positive(
    meta: dict[str, object], field: str, problems: list[str]
) -> float | None:
    if _is_empty(meta.get(field)):
        problems.append(f"{SHEET_META}: {field} is required")
        return None
    return _optional_positive(meta, field, problems)


def _emergency_months(meta: dict[str, object], problems: list[str]) -> int | None:
    if _is_empty(meta.get("emergency_months")):
        problems.append(f"{SHEET_META}: emergency_months is required")
        return None
    number = _number(meta["emergency_months"])
    if (
        number is None
        or number != int(number)
        or not MIN_EMERGENCY_MONTHS <= number <= MAX_EMERGENCY_MONTHS
    ):
        problems.append(
            f"{SHEET_META}: emergency_months must be a whole number "
            f"from {MIN_EMERGENCY_MONTHS} to {MAX_EMERGENCY_MONTHS}"
        )
        return None
    return int(number)


def _target_date(
    meta: dict[str, object], today: date, problems: list[str]
) -> date | None:
    if _is_empty(meta.get("target_date")):
        return None
    parsed = _date(meta["target_date"])
    if parsed is None or parsed <= today:
        problems.append(f"{SHEET_META}: target_date must be a date after today")
        return None
    return parsed


def _emergency_account(
    meta: dict[str, object], asset_accounts: set[str], problems: list[str]
) -> str | None:
    if _is_empty(meta.get("emergency_account")):
        problems.append(f"{SHEET_META}: emergency_account is required")
        return None
    account = str(meta["emergency_account"]).strip()
    if account not in asset_accounts:
        known = ", ".join(sorted(asset_accounts)) or "none"
        problems.append(
            f"{SHEET_META}: emergency_account does not match an asset account "
            f"(known accounts: {known})"
        )
        return None
    return account


def check_plan(
    plan: PlanFile, *, today: date, asset_accounts: set[str]
) -> tuple[Goal | None, list[str]]:
    """The goal to load and no problems, or `None` and every problem found."""
    problems: list[str] = []
    first_seen: dict[tuple[str, str, str], int] = {}
    for item in plan.items:
        problems.extend(_item_problems(item, first_seen))

    meta = plan.meta
    goal_amount = _required_positive(meta, "goal_amount", problems)
    usd_to_pen = _required_positive(meta, "usd_to_pen", problems)
    months = _emergency_months(meta, problems)
    basis = str(meta.get("emergency_basis") or "").strip()
    if basis not in EMERGENCY_BASES:
        problems.append(f"{SHEET_META}: emergency_basis must be all or fixed_only")
    account = _emergency_account(meta, asset_accounts, problems)
    target = _target_date(meta, today, problems)
    income_pen = _optional_positive(meta, "income_pen_override", problems)
    income_usd = _optional_positive(meta, "income_usd_override", problems)

    if problems or None in (goal_amount, usd_to_pen, months, account):
        return None, problems
    assert goal_amount is not None and usd_to_pen is not None
    assert months is not None and account is not None
    return (
        Goal(
            goal_amount=goal_amount,
            usd_to_pen=usd_to_pen,
            emergency_months=months,
            emergency_basis=basis,
            emergency_account=account,
            target_date=target,
            income_pen_override=income_pen,
            income_usd_override=income_usd,
        ),
        [],
    )
