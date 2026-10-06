-- silver.goal_balances: What the savings projection starts from (T65, ADR 0048): per user,
-- bucket and currency, what the emergency account (`emergency`), the other liquid accounts
-- (`other_liquid`) and the investments (`risk`) hold at the last closed month, plus the
-- monthly essential spending (`essential`) that sizes the emergency target.
-- Replaced as one set per user on every `make forecast`.
--
-- The bronze table only exists once a projection has run; until then this is an
-- empty table with the same columns, same pattern as goal_projection.sql.

with source_rows as (

    {% if bronze_table_exists('goal_balances') %}

        select
            user_id,
            run_month,
            bucket,
            currency,
            amount,
            created_at
        from {{ source('bronze', 'goal_balances') }}

    {% else %}

        select
            null::varchar as user_id,
            null::date as run_month,
            null::varchar as bucket,
            null::varchar as currency,
            null::decimal(18, 2) as amount,
            null::timestamp with time zone as created_at
        where false

    {% endif %}

)

select * from source_rows
