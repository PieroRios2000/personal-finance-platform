-- gold.fct_spend_forecast: every forecast run, past and future (T59, ADR 0048, spec 3.2).
--
-- Grain: one row per user, `run_month`, `kind`, category, currency and `target_month`.
-- `kind = 'backtest'` is a one-step forecast of a month that already closed, made
-- without it, with its `actual`; `kind = 'forecast'` looks ahead (horizon 1 to 36) and
-- its `actual` is null. `has_interval` is false where the backtest could not measure one
-- (beyond 12 months, or too few errors): the point forecast alone, never an extrapolation.
-- Every run is kept, so the forecast made last month can be compared with the actual that
-- arrives this month (T62).
--
-- Carries `user_id` for row-level security (ADR 0036). Not a calendar-month fact: it
-- has no `calendar_*` columns, so the calendar filters do not apply to it.

select
    user_id,
    run_month,
    kind,
    category,
    currency,
    target_month,
    horizon,
    model_name,
    p10,
    p50,
    p90,
    actual,
    created_at,
    p10 is not null and p90 is not null as has_interval
from {{ ref('spend_forecasts') }}
