-- silver.emergency_fund: The emergency fund per scenario (T60, ADR 0048, spec 4.4): target,
-- bucket, gap, months to fill, coverage, and the sanity flags, in US dollars.
-- Replaced as one set per user on every `make forecast`.
--
-- The bronze table only exists once a projection has run; until then this is an
-- empty table with the same columns, same pattern as spend_forecasts.sql.

with source_rows as (

    {% if bronze_table_exists('emergency_fund') %}

        select
            user_id,
            run_month,
            scenario,
            target,
            bucket,
            gap,
            months_to_fill,
            months_covered,
            months_of_income,
            savings_rate,
            essential_over_income,
            target_over_two_years_income,
            balance_mismatch,
            mismatch_months,
            months_checked,
            avg_net_flow,
            avg_balance_change,
            created_at
        from {{ source('bronze', 'emergency_fund') }}

    {% else %}

        select
            null::varchar as user_id,
            null::date as run_month,
            null::varchar as scenario,
            null::decimal(18, 2) as target,  -- noqa: RF04
            null::decimal(18, 2) as bucket,
            null::decimal(18, 2) as gap,
            null::integer as months_to_fill,
            null::double as months_covered,
            null::double as months_of_income,
            null::double as savings_rate,
            null::boolean as essential_over_income,
            null::boolean as target_over_two_years_income,
            null::boolean as balance_mismatch,
            null::integer as mismatch_months,
            null::integer as months_checked,
            null::decimal(18, 2) as avg_net_flow,
            null::decimal(18, 2) as avg_balance_change,
            null::timestamp with time zone as created_at
        where false

    {% endif %}

)

select * from source_rows
