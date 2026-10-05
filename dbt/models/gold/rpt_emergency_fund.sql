-- gold.rpt_emergency_fund: The emergency fund per scenario (T60, ADR 0048, spec 4.4): target,
-- bucket, gap, months to fill, coverage, and the sanity flags, in US dollars.
--
-- Carries `user_id` for row-level security (ADR 0036). Not a calendar-month table: no
-- `calendar_*` columns, so the calendar filters do not apply to it.

select
    user_id,
    run_month,
    scenario,
    target,
    bucket,
    gap,
    months_to_fill,
    months_covered,
    months_of_income,
    savings_rate,
    essential_over_income,
    target_over_two_years_income,
    balance_mismatch,
    mismatch_months,
    months_checked,
    avg_net_flow,
    avg_balance_change,
    created_at
from {{ ref('emergency_fund') }}
