-- silver.goal_headroom: The adjust view (T60, ADR 0048, spec 4.5): per category, the forecast
-- above the owner's own usual (25th percentile of the last 12 months) in US dollars; `currency`
-- is the currency the category is charged in.
-- Replaced as one set per user on every `make forecast`.
--
-- The bronze table only exists once a projection has run; until then this is an
-- empty table with the same columns, same pattern as spend_forecasts.sql.

with source_rows as (

    {% if bronze_table_exists('goal_headroom') %}

        select
            user_id,
            run_month,
            category,
            currency,
            forecast,
            reference,
            headroom,
            share,
            created_at
        from {{ source('bronze', 'goal_headroom') }}

    {% else %}

        select
            null::varchar as user_id,
            null::date as run_month,
            null::varchar as category,
            null::varchar as currency,
            null::decimal(18, 2) as forecast,
            null::decimal(18, 2) as reference,
            null::decimal(18, 2) as headroom,
            null::double as share,  -- noqa: RF04
            null::timestamp with time zone as created_at
        where false

    {% endif %}

)

select * from source_rows
