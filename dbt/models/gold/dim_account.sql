-- gold.dim_account: one row per account_id that appears in
-- silver.transactions (T23).
--
-- Grain: one row per `account_id`, confirmed (not assumed -- see ADR 0020)
-- as a plain dimension with no slowly-changing-dimension handling.
-- account_kind and bank are set once per parser (ADR 0015) and never vary
-- for a given account_id after the fact, so there is nothing for an SCD to
-- version.
--
-- `group by` + `max()`, not `select distinct`: the same "safe by
-- construction" precedent silver.transactions' own account_kinds CTE and
-- internal_transfer_matches.sql already use (ADR 0015). account_id is an
-- HMAC keyed off bank + the real account number, so bank/account_last4/
-- account_kind are already constant per account_id in practice; max() makes
-- that agreement load-bearing for this dimension's own one-row-per-account
-- grain, rather than assuming every row happens to agree.

select
    account_id,
    max(bank) as bank,
    max(account_last4) as account_last4,
    max(account_kind) as account_kind
from {{ ref('transactions') }}
group by account_id
