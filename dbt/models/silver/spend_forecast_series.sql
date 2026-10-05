-- silver.spend_forecast_series: how much to trust each forecast series (T59, ADR 0048,
-- spec 4.2). One row per user, run, category and currency: the selected model, months of
-- history, backtest origins, MAE relative to the baseline (1.0 = no better), the
-- interval coverage (optimistic: measured on the errors the interval came from) and the
-- flags `baseline_used` and `low_history`.
--
-- Empty (same columns) until `make forecast` has run, like spend_forecasts.sql.

with source_rows as (

    {% if bronze_table_exists('spend_forecast_series') %}

        select
            user_id,
            run_month,
            category,
            currency,
            model_name,
            baseline_used,
            low_history,
            n_months,
            n_origins,
            mae_rel,
            coverage,
            created_at
        from {{ source('bronze', 'spend_forecast_series') }}

    {% else %}

        select
            null::varchar as user_id,
            null::date as run_month,
            null::varchar as category,
            null::varchar as currency,
            null::varchar as model_name,
            null::boolean as baseline_used,
            null::boolean as low_history,
            null::integer as n_months,
            null::integer as n_origins,
            null::double as mae_rel,
            null::double as coverage,
            null::timestamp with time zone as created_at
        where false

    {% endif %}

)

select * from source_rows
