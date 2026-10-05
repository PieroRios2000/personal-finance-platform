-- gold.rpt_goal_balances: What the savings projection starts from (T65, ADR 0048): one row per
-- user, bucket (`emergency`, `other_liquid`, `risk`, and `essential` for the monthly essential
-- spending) and currency, at the last closed month.
--
-- Carries `user_id` for row-level security (ADR 0036). Not a calendar-month table: no
-- `calendar_*` columns, so the calendar filters do not apply to it.

select
    user_id,
    run_month,
    bucket,
    currency,
    amount,
    created_at
from {{ ref('goal_balances') }}
