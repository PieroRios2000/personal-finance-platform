-- gold.rpt_goal_cashflow: The pieces behind the savings projection (T65, ADR 0048): one row
-- per user, scenario, month index (1 to 120) and currency, in the currency they were earned or
-- charged in. The dashboard's goal dataset recombines them under its own exchange rate.
--
-- Carries `user_id` for row-level security (ADR 0036). Not a calendar-month table: no
-- `calendar_*` columns, so the calendar filters do not apply to it.

select
    user_id,
    run_month,
    scenario,
    month_index,
    month,
    currency,
    income,
    fixed,
    variable,
    created_at
from {{ ref('goal_cashflow') }}
