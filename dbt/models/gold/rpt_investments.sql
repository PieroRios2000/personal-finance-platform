-- gold.rpt_investments: each fund's month with its return, and its calendar attributes.
--
-- The reporting layer (T34): the monthly investment fact joined to the shared calendar
-- (`dim_date`), so every BI dataset carries the same `calendar_*` columns and one
-- calendar filter applies to all of them. A table (dbt-duckdb cannot create a view
-- in the attached Postgres), rebuilt with every run: the star schema (the facts and
-- dimensions) stays untouched for dbt and the models.
--
-- Only closed months: rows of the current month are left out
-- (`first_day_of_current_month`), so a partial month never mixes with complete ones.

select
    facts.*,
    calendar.year_number as calendar_year,
    calendar.year_quarter as calendar_quarter,
    calendar.month_label as calendar_month,
    calendar.month_name as calendar_month_name,
    calendar.day_name as calendar_day_name
from {{ ref('fct_investment_monthly') }} as facts
inner join {{ ref('dim_date') }} as calendar
    on facts.month_start = calendar.date
where facts.month_start < {{ first_day_of_current_month() }}
