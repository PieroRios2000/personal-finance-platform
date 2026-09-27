-- gold.dim_category: the fixed list of spending/income categories (T51, ADR 0043).
--
-- A plain seed (dbt/seeds/category.csv), not derived from any fact: the list is the
-- owner's own short, closed set (13 categories plus a catch-all "Otros"), decided once,
-- not discovered from the data. The natural key is the category name itself -- the
-- same reasoning as every other dimension in this star schema (fact_transactions.sql):
-- no separate master-data source to generate a surrogate key against.

select
    category,
    description
from {{ ref('category') }}
