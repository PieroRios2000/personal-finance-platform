-- gold.rpt_category_variance: where the last closed month ran above what the category's
-- own history predicted (T59, ADR 0048, spec 4.3).
--
-- Grain: one row per user, category and currency of the latest forecast run. The actual
-- of the run's month is compared with the forecast made WITHOUT it (a backtest row, so
-- it works from the first run): `above` when it is over `p90`, `below` when under `p10`,
-- `within` otherwise, `no_interval` when the series had too few errors for an interval.
-- "Above" therefore means above what the category's own history predicted with its own
-- noise, not above a budget. `months_above_last_6` counts the last six closed months
-- (this one included) that were above their interval. The interval is the series' final
-- error quantiles applied to every month, so it is optimistic. Fixed items have their
-- own table (rpt_fixed_expenses).
--
-- Carries `user_id` for row-level security (ADR 0036). Not monthly, so no `calendar_*`
-- columns.

{% set recent_months = 6 %}

with latest_run as (

    select
        user_id,
        max(run_month) as run_month
    from {{ ref('spend_forecasts') }}
    group by user_id

),

backtest as (

    select
        spend_forecasts.user_id,
        spend_forecasts.run_month,
        spend_forecasts.category,
        spend_forecasts.currency,
        spend_forecasts.target_month,
        spend_forecasts.model_name,
        spend_forecasts.p10,
        spend_forecasts.p50,
        spend_forecasts.p90,
        spend_forecasts.actual
    from {{ ref('spend_forecasts') }}
    inner join latest_run
        on
            spend_forecasts.user_id = latest_run.user_id
            and spend_forecasts.run_month = latest_run.run_month
    where spend_forecasts.kind = 'backtest'

),

recent as (

    select
        user_id,
        category,
        currency,
        count(*) filter (where actual > p90) as months_above_last_6
    from backtest
    where target_month > cast(run_month - interval {{ recent_months }} month as date)
    group by user_id, category, currency

),

latest_month as (

    select *
    from backtest
    where target_month = run_month

)

select
    latest_month.user_id,
    latest_month.category,
    latest_month.currency,
    latest_month.run_month,
    latest_month.target_month,
    latest_month.model_name,
    latest_month.actual,
    latest_month.p10,
    latest_month.p50,
    latest_month.p90,
    recent.months_above_last_6,
    latest_month.actual - latest_month.p50 as difference,
    case
        when latest_month.p10 is null or latest_month.p90 is null then 'no_interval'
        when latest_month.actual > latest_month.p90 then 'above'
        when latest_month.actual < latest_month.p10 then 'below'
        else 'within'
    end as status
from latest_month
inner join recent
    on
        latest_month.user_id = recent.user_id
        and latest_month.category = recent.category
        and latest_month.currency = recent.currency
