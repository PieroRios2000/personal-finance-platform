-- gold.rpt_goal_headroom: The adjust view (T60, ADR 0048, spec 4.5): per category, the forecast
-- above the owner's own usual (25th percentile of the last 12 months) in US dollars.
-- `source_currency` is the currency the category is charged in; it is not called `currency`
-- because every amount here is in dollars, and the dashboard's Currency filter must not
-- drop the rows of a category charged in the other currency.
--
-- Carries `user_id` for row-level security (ADR 0036). Not a calendar-month table: no
-- `calendar_*` columns, so the calendar filters do not apply to it.

select
    user_id,
    run_month,
    category,
    currency as source_currency,
    forecast,
    reference,
    headroom,
    share,
    created_at
from {{ ref('goal_headroom') }}
