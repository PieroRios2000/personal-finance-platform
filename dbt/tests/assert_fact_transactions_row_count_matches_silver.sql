-- gold.fact_transactions must have exactly one row per silver.transactions
-- row (T23's own "1:1 fact" acceptance criterion) -- this is the standing
-- proof, run every `dbt build`, not just checked once in a PR description.
--
-- A singular test cross-joining two single-row counts, mirroring this
-- project's own established pattern for a one-off "compare two numbers"
-- check (no dbt package dependency; see
-- assert_transactions_business_key_is_unique.sql).

with fact_count as (

    select count(*) as row_count
    from {{ ref('fact_transactions') }}

),

silver_count as (

    select count(*) as row_count
    from {{ ref('transactions') }}

)

select
    fact_count.row_count as fact_row_count,
    silver_count.row_count as silver_row_count
from fact_count
cross join silver_count
where fact_count.row_count != silver_count.row_count
