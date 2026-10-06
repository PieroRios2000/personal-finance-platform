-- gold.rpt_forecast_realized: how an older forecast did once its month closed (T62, ADR 0048,
-- spec 3.2 "Monitoring").
--
-- Grain: one row per user, `run_month`, category, currency and `target_month` of a
-- `forecast` row whose month has since closed. The actual comes from the latest run that
-- backtested that month (`fct_spend_forecast`), so a month that has not closed yet has no
-- row. `realized_error` is the miss in the series' own currency; `backtest_mae` is the
-- typical miss of the same run's backtest rows, in the same unit, and `error_ratio` is the
-- first over the second: near 1 the forecast did as well as it did when it was tested,
-- well above it did worse (null when the run had no backtest or it never missed, and null
-- past horizon 1: the backtest MAE is a one-step miss, a longer forecast is expected to miss
-- more and would read as worse for no reason).
-- `status` is `above` over `p90`, `below` under `p10`, `within` otherwise and
-- `no_interval` when the run had no interval. The owner judges it; there is no drift test
-- on about two dozen points per series (ADR 0046).
--
-- `source` says where the row comes from. `realized` is the above: a forecast made before
-- the month closed. `backtest` (T64) is a one-step forecast of a past month, made without it
-- and with the actual known, from the latest run: it shows how the model did in the past
-- while no `realized` row exists yet (a second monthly run is needed for the first one).
-- A backtest row has no `backtest_mae` or `error_ratio`: its miss is the backtest.
--
-- Carries `user_id` for row-level security (ADR 0036). Not monthly, so no `calendar_*`
-- columns.

with closed_months as (

    select
        user_id,
        run_month,
        category,
        currency,
        target_month,
        actual,
        row_number() over (
            partition by user_id, category, currency, target_month
            order by run_month desc
        ) as recency
    from {{ ref('fct_spend_forecast') }}
    where kind = 'backtest' and actual is not null

),

backtest_miss as (

    select
        user_id,
        run_month,
        category,
        currency,
        avg(abs(actual - p50)) as backtest_mae
    from {{ ref('fct_spend_forecast') }}
    where kind = 'backtest' and actual is not null
    group by user_id, run_month, category, currency

),

realized as (

    select
        forecast.user_id,
        forecast.run_month,
        forecast.category,
        forecast.currency,
        forecast.target_month,
        forecast.horizon,
        forecast.model_name,
        forecast.p10,
        forecast.p50,
        forecast.p90,
        closed_months.actual,
        backtest_miss.backtest_mae,
        abs(closed_months.actual - forecast.p50) as realized_error,
        case
            when forecast.horizon = 1
                then
                    abs(closed_months.actual - forecast.p50)
                    / nullif(backtest_miss.backtest_mae, 0)
        end as error_ratio,
        'realized' as source  -- noqa: RF04
    from {{ ref('fct_spend_forecast') }} as forecast
    inner join closed_months
        on
            forecast.user_id = closed_months.user_id
            and forecast.category = closed_months.category
            and forecast.currency = closed_months.currency
            and forecast.target_month = closed_months.target_month
            and closed_months.recency = 1
    left join backtest_miss
        on
            forecast.user_id = backtest_miss.user_id
            and forecast.run_month = backtest_miss.run_month
            and forecast.category = backtest_miss.category
            and forecast.currency = backtest_miss.currency
    where forecast.kind = 'forecast'

),

backtested as (

    select
        forecast.user_id,
        forecast.run_month,
        forecast.category,
        forecast.currency,
        forecast.target_month,
        forecast.horizon,
        forecast.model_name,
        forecast.p10,
        forecast.p50,
        forecast.p90,
        forecast.actual,
        null::numeric as backtest_mae,
        abs(forecast.actual - forecast.p50) as realized_error,
        null::numeric as error_ratio,
        'backtest' as source  -- noqa: RF04
    from {{ ref('fct_spend_forecast') }} as forecast
    inner join closed_months
        on
            forecast.user_id = closed_months.user_id
            and forecast.run_month = closed_months.run_month
            and forecast.category = closed_months.category
            and forecast.currency = closed_months.currency
            and forecast.target_month = closed_months.target_month
            and closed_months.recency = 1
    where forecast.kind = 'backtest'

),

combined as (

    select * from realized
    union all
    select * from backtested

)

select
    user_id,
    run_month,
    category,
    currency,
    target_month,
    horizon,
    model_name,
    p10,
    p50,
    p90,
    actual,
    backtest_mae,
    realized_error,
    error_ratio,
    source,  -- noqa: RF04
    case
        when p10 is null or p90 is null then 'no_interval'
        when actual > p90 then 'above'
        when actual < p10 then 'below'
        else 'within'
    end as status
from combined
