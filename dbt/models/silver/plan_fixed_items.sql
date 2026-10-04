-- silver.plan_fixed_items: the owner's own classification of recurring expenses (T57,
-- ADR 0048) -- a lookup, not a fact: one row per (bank, description, currency), `kind`
-- fixed / variable / ignore and the monthly `expected_amount` he confirmed. Replaced
-- wholesale on every `make import-plan` (`lakehouse.bronze.replace_plan`).
--
-- The bronze table only exists once a plan has been imported; until then this is an
-- empty table with the same columns, same pattern as category_labels.sql.

with source_rows as (

    {% if bronze_table_exists('plan_fixed_items') %}

        select
            user_id,
            bank,
            description,
            currency,
            category,
            months_seen,
            typical_amount,
            proposed_kind,
            kind,
            expected_amount,
            note,
            loaded_at
        from {{ source('bronze', 'plan_fixed_items') }}

    {% else %}

        select
            null::varchar as user_id,
            null::varchar as bank,
            null::varchar as description,
            null::varchar as currency,
            null::varchar as category,
            null::integer as months_seen,
            null::decimal(18, 2) as typical_amount,
            null::varchar as proposed_kind,
            null::varchar as kind,
            null::decimal(18, 2) as expected_amount,
            null::varchar as note,
            null::timestamp with time zone as loaded_at
        where false

    {% endif %}

)

select * from source_rows
