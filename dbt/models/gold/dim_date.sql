-- gold.dim_date: one row per calendar date that appears in
-- silver.transactions (T23).
--
-- Grain: one row per distinct `date`. Derived straight from the dates that
-- actually occur, not a generated calendar spine -- the same "no columns or
-- rows nothing asked for" discipline dbt-silver.md documents for
-- silver.transactions itself. A spine would need an arbitrary start/end
-- range to generate for a project with no fixed reporting horizon; this
-- dimension only ever needs to resolve fact_transactions' own `date`
-- values, which selecting them straight out of the source already
-- guarantees, with no gap possible.
--
-- The date-part columns below are standard, cheap-to-derive attributes a BI
-- tool or a "spend by month" query wants without re-deriving them per query
-- -- nothing speculative beyond that (no fiscal calendar, no holidays).

with distinct_dates as (

    select distinct date
    from {{ ref('transactions') }}

)

select
    date,
    extract(year from date) as year_number,
    extract(quarter from date) as quarter_number,
    extract(month from date) as month_number,
    strftime(date, '%B') as month_name,
    extract(day from date) as day_number,
    strftime(date, '%A') as day_name,
    -- DuckDB's dayofweek(): 0 = Sunday .. 6 = Saturday.
    dayofweek(date) in (0, 6) as is_weekend
from distinct_dates
