-- gold.rpt_goal_projection: The savings-goal path (T60, ADR 0048, spec 4.4): one row per user,
-- scenario, line and month index (0 = the last closed month, to 120), in US dollars.
-- `emergency` is the emergency bucket, `goal_progress` what counts toward the goal.
--
-- Carries `user_id` for row-level security (ADR 0036). Not a calendar-month table: no
-- `calendar_*` columns, so the calendar filters do not apply to it.

select
    user_id,
    run_month,
    scenario,
    line,
    month_index,
    month,
    emergency,
    goal_progress,
    created_at
from {{ ref('goal_projection') }}
