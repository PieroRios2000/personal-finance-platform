-- gold.rpt_category_forecast: what the dashboard shows of the forecast (T61, ADR 0048): the
-- latest run only, one row per user, category, currency and horizon (1 to 3 months ahead),
-- with the interval and how far to trust the series (model, whether the median baseline was
-- used, months of history, `mae_rel`, `coverage`). Older runs and the backtest rows stay in
-- `fct_spend_forecast`; the realized-vs-backtest monitor reads those.
--
-- Carries `user_id` for row-level security (ADR 0036). Not a calendar-month table: no
-- `calendar_*` columns, so the calendar filters do not apply to it.

with latest_run as (

    select
        user_id,
        max(run_month) as run_month
    from {{ ref('fct_spend_forecast') }}
    group by user_id

)

select
    fct_spend_forecast.user_id,
    fct_spend_forecast.run_month,
    fct_spend_forecast.category,
    fct_spend_forecast.currency,
    fct_spend_forecast.target_month,
    fct_spend_forecast.horizon,
    fct_spend_forecast.model_name,
    fct_spend_forecast.p10,
    fct_spend_forecast.p50,
    fct_spend_forecast.p90,
    rpt_forecast_series_quality.baseline_used,
    rpt_forecast_series_quality.low_history,
    rpt_forecast_series_quality.n_months,
    rpt_forecast_series_quality.mae_rel,
    rpt_forecast_series_quality.coverage
from {{ ref('fct_spend_forecast') }}
inner join latest_run
    on
        fct_spend_forecast.user_id = latest_run.user_id
        and fct_spend_forecast.run_month = latest_run.run_month
left join {{ ref('rpt_forecast_series_quality') }}
    on
        fct_spend_forecast.user_id = rpt_forecast_series_quality.user_id
        and fct_spend_forecast.run_month = rpt_forecast_series_quality.run_month
        and fct_spend_forecast.category = rpt_forecast_series_quality.category
        and fct_spend_forecast.currency = rpt_forecast_series_quality.currency
where fct_spend_forecast.kind = 'forecast'
