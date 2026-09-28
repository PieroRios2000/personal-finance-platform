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
-- assigns afterwards. No confirmed label yet, but the trained model has a batch
-- prediction for it (T54, ADR 0045, `silver.category_predictions`, same join key):
-- that prediction is used instead, still coalesced to 'Sin categorizar' if neither
-- exists. `category_confirmed` tells the two apart -- true only for the owner's own
-- label, never for a prediction, so nothing built on this reads a proposal as if the
-- owner had actually confirmed it (ADR 0043's "propose, never assign silently",
-- carried one layer further).

select
    facts.*,
    calendar.year_number as calendar_year,
    calendar.year_quarter as calendar_quarter,
    calendar.month_label as calendar_month,
    calendar.month_name as calendar_month_name,
    calendar.day_name as calendar_day_name,
    coalesce(labels.category, predictions.category, 'Sin categorizar') as category,
    labels.category is not null as category_confirmed
from {{ ref('fact_transactions') }} as facts
inner join {{ ref('dim_date') }} as calendar
    on facts.date = calendar.date
left join {{ ref('category_labels') }} as labels
    on
        facts.user_id = labels.user_id
        and facts.bank = labels.bank
        and facts.description = labels.description
left join {{ ref('category_predictions') }} as predictions
    on
        facts.user_id = predictions.user_id
        and facts.bank = predictions.bank
        and facts.description = predictions.description
where facts.date < {{ first_day_of_current_month() }}
