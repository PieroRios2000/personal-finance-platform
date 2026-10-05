-- silver.plan_goal: the owner's savings goal and emergency-fund settings (T57, ADR 0048),
-- one row per user. The goal is always in US dollars (`goal_currency`); `usd_to_pen` is
-- the soles one dollar costs, and the only conversion the plan uses. Replaced wholesale
-- on every `make import-plan`.
--
-- Empty (same columns) until a plan has been imported, like plan_fixed_items.sql.

with source_rows as (

    {% if bronze_table_exists('plan_goal') %}

        select
            user_id,
            goal_amount,
            goal_currency,
            usd_to_pen,
            emergency_months,
            emergency_basis,
            emergency_account,
            target_date,
            income_pen_override,
            income_usd_override,
            loaded_at
        from {{ source('bronze', 'plan_goal') }}

    {% else %}

        select
            null::varchar as user_id,
            null::decimal(18, 2) as goal_amount,
            null::varchar as goal_currency,
            null::double as usd_to_pen,
            null::integer as emergency_months,
            null::varchar as emergency_basis,
            null::varchar as emergency_account,
            null::date as target_date,
            null::decimal(18, 2) as income_pen_override,
            null::decimal(18, 2) as income_usd_override,
            null::timestamp with time zone as loaded_at
        where false

    {% endif %}

)

select * from source_rows
