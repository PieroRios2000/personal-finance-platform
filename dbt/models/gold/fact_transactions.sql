-- gold.fact_transactions: one row per silver.transactions business key
-- (T23) -- the exact same grain (account_id + date + amount + normalized
-- description + occurrence_number, T20), since this model is a straight
-- select with no join that could fan a row out. Foreign keys into every
-- dimension below are the natural keys themselves (account_id, bank,
-- user_id, date): this project has no separate master-data source for
-- accounts/banks/users to generate a surrogate key against, and every one
-- of those dimensions is itself derived from this exact source
-- (dim_account.sql, dim_bank.sql, dim_user.sql, dim_date.sql), so a natural
-- key resolves every FK by construction, and a surrogate one would only add
-- an extra hash/sequence with nothing real to protect against.
--
-- `amount`/`currency`/`date` stay as measures/degenerate attributes, exactly
-- as silver carries them. `currency` is never collapsed or converted here or
-- anywhere else in this project -- no FX, ever (tasks/plan-phase2.md's own
-- architecture decisions; Piero's explicit call) -- every currency-sliced
-- query stays sliced.
--
-- flow_type (T23, ADR 0020): direction only, derived from account_kind +
-- amount's sign, never each bank's own raw sign convention directly -- BCP
-- (asset) reads a negative amount as money out, Scotiabank (liability)
-- reads a positive amount as a charge added to debt owed (ADR 0015): the
-- opposite raw convention for the same real-world "money left my pocket"
-- fact.
--   asset    + positive -> ingreso
--   asset    + negative -> egreso
--   liability + positive (a charge)          -> egreso
--   liability + negative (a payment/credit)  -> pago
-- `pago` is its own bucket, not folded into `ingreso`: a negative-signed
-- liability movement is usually a transfer from the user's own other
-- account (already flagged separately by is_internal_transfer, T18b) or a
-- refund -- genuinely ambiguous which, so it is never counted as income
-- either way. Every amount is guaranteed non-zero
-- (ingestion.schema.Transaction rejects a zero amount) and account_kind is
-- guaranteed to be exactly 'asset' or 'liability' (schema.yml's own
-- accepted_values test on silver.transactions), so these four branches are
-- exhaustive -- deliberately no catch-all `else`, so a value schema.yml's
-- own upstream tests didn't anticipate surfaces as a loud null
-- (this model's own not_null test on flow_type) rather than silently
-- landing in the wrong bucket.
--
-- flow_type is direction only -- it doesn't anticipate or touch Phase 3's
-- future dim_category (tasks/plan-phase2.md's own architecture decisions;
-- no dim_category exists in this project yet, on purpose).

select
    silver_transactions.user_id,
    silver_transactions.account_id,
    silver_transactions.bank,
    silver_transactions.date,
    silver_transactions.amount,
    silver_transactions.currency,
    silver_transactions.description,
    silver_transactions.occurrence_number,
    silver_transactions.is_internal_transfer,
    case
        when
            silver_transactions.account_kind = 'asset'
            and silver_transactions.amount > 0
            then 'ingreso'
        when
            silver_transactions.account_kind = 'asset'
            and silver_transactions.amount < 0
            then 'egreso'
        when
            silver_transactions.account_kind = 'liability'
            and silver_transactions.amount > 0
            then 'egreso'
        when
            silver_transactions.account_kind = 'liability'
            and silver_transactions.amount < 0
            then 'pago'
    end as flow_type
from {{ ref('transactions') }} as silver_transactions
