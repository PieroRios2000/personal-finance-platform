-- gold.dim_date: the calendar every BI filter and chart shares (T23, widened in
-- T34).
--
-- Grain: one row per calendar day from the first day of the first month to the last
-- day of the last month that any fact has data for: a movement date
-- (silver.transactions), a statement month (fct_account_balance_monthly) or an
-- investment month (fct_investment_monthly). It started as only the dates that had a
-- movement; the range is now continuous, so a month or a day with no activity still
-- exists (a chart can show it empty, a filter can select it), and the balances and
-- investments join the same calendar as the movements. The range comes from the data,
-- not from a hard-coded start and end.
--
-- The date-part columns are the attributes a BI tool wants without re-deriving them
-- per query (`year_month` like `2026-03`, `year_quarter` like `2026-Q1`) --
-- nothing speculative beyond that (no fiscal calendar, no holidays).

with data_range as (

    select
        min(seen) as first_date,
        max(seen) as last_date
    from (
        select date as seen from {{ ref('transactions') }}
        union all
        select month_start as seen from {{ ref('fct_account_balance_monthly') }}
        union all
        select month_start as seen from {{ ref('fct_investment_monthly') }}
    ) as seen_dates

),

calendar as (

    select
        cast(
            unnest(
                generate_series(
                    date_trunc('month', first_date),
                    last_day(last_date),
                    interval 1 day
                )
            ) as date
        ) as date
    from data_range

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
    dayofweek(date) in (0, 6) as is_weekend,
    cast(date_trunc('month', date) as date) as month_start,
    strftime(date, '%Y-%m') as year_month,
    strftime(date, '%Y') || '-Q' || cast(extract(quarter from date) as varchar)
        as year_quarter
from calendar
