-- gold.rpt_goal_summary: The savings-goal answer per scenario and line (T60, ADR 0048): months
-- to the goal (null = not reached in 120 months), the saving it needs and the one projected, in
-- US dollars.
--
-- Carries `user_id` for row-level security (ADR 0036). Not a calendar-month table: no
-- `calendar_*` columns, so the calendar filters do not apply to it.

select
    user_id,
    run_month,
    scenario,
    line,
    months_to_goal,
    reached_month,
    required_monthly_saving,
    projected_monthly_saving,
    gap,
    headroom_share_of_gap,
    created_at
from {{ ref('goal_summary') }}
