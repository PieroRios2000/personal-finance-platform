-- silver.goal_summary: The savings-goal answer per scenario and line (T60, ADR 0048): months to
-- the goal (null = not reached in 120 months), the saving it needs and the one projected, in US
-- dollars.
-- Replaced as one set per user on every `make forecast`.
--
-- The bronze table only exists once a projection has run; until then this is an
-- empty table with the same columns, same pattern as spend_forecasts.sql.

with source_rows as (

    {% if bronze_table_exists('goal_summary') %}

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
        from {{ source('bronze', 'goal_summary') }}

    {% else %}

        select
            null::varchar as user_id,
            null::date as run_month,
            null::varchar as scenario,
            null::varchar as line,  -- noqa: RF04
            null::integer as months_to_goal,
            null::date as reached_month,
            null::decimal(18, 2) as required_monthly_saving,
            null::decimal(18, 2) as projected_monthly_saving,
            null::decimal(18, 2) as gap,
            null::double as headroom_share_of_gap,
            null::timestamp with time zone as created_at
        where false

    {% endif %}

)

select * from source_rows
