-- gold.rpt_balances: each account's declared closing balance per month, with its
-- calendar attributes.
--
-- The reporting layer (T34): the monthly balance fact joined to the shared calendar
-- (`dim_date`), so every BI dataset carries the same `calendar_*` columns and one
-- calendar filter applies to all of them. A table (dbt-duckdb cannot create a view
-- in the attached Postgres), rebuilt with every run: the star schema (the facts and
-- dimensions) stays untouched for dbt and the models.

select
    facts.*,
    calendar.year_number as calendar_year,
    calendar.year_quarter as calendar_quarter,
    calendar.month_label as calendar_month,
    calendar.month_name as calendar_month_name,
    calendar.day_name as calendar_day_name,
    -- 1 = the latest month of the data, 2 = the one before: lets a BI tool show "latest
    -- balance" and "change vs previous month" without a sub-query.
    dense_rank() over (order by facts.month_start desc) as month_recency
from {{ ref('fct_account_balance_monthly') }} as facts
inner join {{ ref('dim_date') }} as calendar
    on facts.month_start = calendar.date
