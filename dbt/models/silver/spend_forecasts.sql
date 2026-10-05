-- silver.spend_forecasts: the forecast runs as typed rows (T59, ADR 0048, spec 4.2).
-- One row per user, run (the first day of the last closed month), `kind`, category,
-- currency and target month; `kind` is 'backtest' (a past one-step forecast, `actual`
-- filled) or 'forecast' (the next months, `actual` null). `p10` and `p90` are null for a
-- series with too few backtest errors for an interval.
--
-- The bronze table only exists once `make forecast` has run; until then this is an
-- empty table with the same columns, same pattern as plan_goal.sql.

with source_rows as (

    {% if bronze_table_exists('spend_forecasts') %}

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
            created_at
        from {{ source('bronze', 'spend_forecasts') }}

    {% else %}

        select
            null::varchar as user_id,
            null::date as run_month,
            null::varchar as kind,
            null::varchar as category,
            null::varchar as currency,
            null::date as target_month,
            null::integer as horizon,
            null::varchar as model_name,
            null::decimal(18, 2) as p10,
            null::decimal(18, 2) as p50,
            null::decimal(18, 2) as p90,
            null::decimal(18, 2) as actual,
            null::timestamp with time zone as created_at
        where false

    {% endif %}

)

select * from source_rows
