-- silver.goal_projection: The savings-goal path (T60, ADR 0048, spec 4.4): one row per user,
-- scenario, line and month index (0 = the last closed month, to 120), in US dollars.
-- `emergency` is the emergency bucket, `goal_progress` what counts toward the goal.
-- Replaced as one set per user on every `make forecast`.
--
-- The bronze table only exists once a projection has run; until then this is an
-- empty table with the same columns, same pattern as spend_forecasts.sql.

with source_rows as (

    {% if bronze_table_exists('goal_projection') %}

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
        from {{ source('bronze', 'goal_projection') }}

    {% else %}

        select
            null::varchar as user_id,
            null::date as run_month,
            null::varchar as scenario,
            null::varchar as line,  -- noqa: RF04
            null::integer as month_index,
            null::date as month,  -- noqa: RF04
            null::decimal(18, 2) as emergency,
            null::decimal(18, 2) as goal_progress,
            null::timestamp with time zone as created_at
        where false

    {% endif %}

)

select * from source_rows
