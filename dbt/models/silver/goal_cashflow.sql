-- silver.goal_cashflow: The pieces behind the savings projection (T65, ADR 0048): per user,
-- scenario, month index (1 to 120) and currency, the income, the fixed spending and the
-- variable spending of that month, in the currency they were earned or charged in. The
-- dashboard recombines them under its own exchange rate, goal and emergency months.
-- Replaced as one set per user on every `make forecast`.
--
-- The bronze table only exists once a projection has run; until then this is an
-- empty table with the same columns, same pattern as goal_projection.sql.

with source_rows as (

    {% if bronze_table_exists('goal_cashflow') %}

        select
            user_id,
            run_month,
            scenario,
            month_index,
            month,
            currency,
            income,
            fixed,
            variable,
            created_at
        from {{ source('bronze', 'goal_cashflow') }}

    {% else %}

        select
            null::varchar as user_id,
            null::date as run_month,
            null::varchar as scenario,
            null::integer as month_index,
            null::date as month,  -- noqa: RF04
            null::varchar as currency,
            null::decimal(18, 2) as income,
            null::decimal(18, 2) as fixed,
            null::decimal(18, 2) as variable,  -- noqa: RF04
            null::timestamp with time zone as created_at
        where false

    {% endif %}

)

select * from source_rows
