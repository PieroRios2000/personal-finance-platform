-- gold.dim_category: the fixed list of spending/income categories (T51, ADR 0043).
--
-- A plain seed (dbt/seeds/category.csv), not derived from any fact: the list is the
-- owner's own short, closed set (5 categories plus a catch-all "Gastos varios"), kept
-- deliberately short (2026-09-27) -- narrowed further only once these stop being
-- enough. The natural key is the category name itself -- the
-- same reasoning as every other dimension in this star schema (fact_transactions.sql):
-- no separate master-data source to generate a surrogate key against.

select
    category,
    description
from {{ ref('category') }}
