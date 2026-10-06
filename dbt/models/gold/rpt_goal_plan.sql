-- gold.rpt_goal_plan: The defaults of the dynamic goal (T65, ADR 0048): one row per user with
-- the goal, the exchange rate and the emergency months of the `Meta` sheet, and the 36 months
-- the forecast looks ahead. The dashboard's goal dataset uses them until a native filter
-- overrides one.
--
-- Carries `user_id` for row-level security (ADR 0036). Not a calendar-month table: no
-- `calendar_*` columns, so the calendar filters do not apply to it.

select
    user_id,
    goal_amount,
    usd_to_pen,
    emergency_months,
    target_date,
    36 as horizon_months
from {{ ref('plan_goal') }}
