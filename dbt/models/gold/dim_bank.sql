-- gold.dim_bank: one row per distinct bank name in silver.transactions
-- (T23).
--
-- Grain: one row per `bank`. Kept as its own dimension, separate from
-- dim_account, so a bank-level query (e.g. "spend by bank by month") can
-- join fact_transactions straight to it without going through
-- account-level detail.

select distinct bank
from {{ ref('transactions') }}
