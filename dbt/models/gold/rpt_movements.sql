-- gold.rpt_movements: every movement with its calendar attributes and its category.
--
-- The reporting layer (T34): the movement fact joined to the shared calendar
-- (`dim_date`), so every BI dataset carries the same `calendar_*` columns and one
-- calendar filter applies to all of them. A table (dbt-duckdb cannot create a view
-- in the attached Postgres), rebuilt with every run: the star schema (the facts and
-- dimensions) stays untouched for dbt and the models.
--
-- Only closed months: rows of the current month are left out
-- (`first_day_of_current_month`), so a partial month never mixes with complete ones.
--
-- `category` (T51, ADR 0043): a left join to the owner's own labels
-- (`silver.category_labels`), on the same `(user_id, bank, description)` the labeling
-- file groups by -- `description` is already `normalize_description()`-d by
-- `silver.transactions`, so it matches without any further cleanup on either side.
-- Deliberately not on `fact_transactions` itself (that model's own comment): the fact
-- table is what the parsers and reconciliation produce, untouched by a label the owner
-- assigns afterwards. Unlabeled, or before any labeling file has ever been imported
-- (the source table doesn't exist yet), a movement reads as 'Sin categorizar' rather
-- than null -- one fewer null check for every chart that groups by category.

select
    facts.*,
    calendar.year_number as calendar_year,
    calendar.year_quarter as calendar_quarter,
    calendar.month_label as calendar_month,
    calendar.month_name as calendar_month_name,
    calendar.day_name as calendar_day_name,
    coalesce(labels.category, 'Sin categorizar') as category
from {{ ref('fact_transactions') }} as facts
inner join {{ ref('dim_date') }} as calendar
    on facts.date = calendar.date
left join {{ ref('category_labels') }} as labels
    on facts.user_id = labels.user_id
    and facts.bank = labels.bank
    and facts.description = labels.description
where facts.date < {{ first_day_of_current_month() }}
