-- Balance reconciliation, re-checked at the model layer (T20).
--
-- `ingestion/reconciliation.py` (T8) already checks this once in Python, at
-- parse time, before a row ever reaches bronze: opening balance + the
-- movements = closing balance. This is the exact same arithmetic, run again
-- here against what actually landed in `silver.transactions` -- specifically
-- to catch anything T20's own incremental MERGE gets wrong (a row silently
-- dropped or duplicated by a bad `unique_key`/`pre_hook` interaction) that a
-- check upstream of the MERGE could never see, since that check runs before
-- the MERGE exists at all.
--
-- Partitioned by currency too (T18c), following assert_statement_continuity.sql's
-- own pattern: a Scotiabank statement writes two bronze.statements rows for
-- one real statement, one per currency (ADR 0012), sharing account_id and
-- period_start/period_end -- summing every transaction between those dates
-- without also matching currency would blend two independent ledgers into
-- one meaningless number.
--
-- A singular test, not a generic one: one query joining two relations, with
-- nothing to parametrize. Severity is dbt's default, `error`.

with statement_totals as (

    select
        user_id,
        account_id,
        currency,
        period_start,
        period_end,
        closing_balance - opening_balance as declared_movement
    from {{ source('bronze', 'statements') }}

),

actual_totals as (

    select
        statement_totals.user_id,
        statement_totals.account_id,
        statement_totals.currency,
        statement_totals.period_start,
        statement_totals.period_end,
        statement_totals.declared_movement,
        coalesce(sum(silver_transactions.amount), 0) as actual_movement
    from statement_totals
    left join {{ ref('transactions') }} as silver_transactions
        on
            statement_totals.user_id = silver_transactions.user_id
            and statement_totals.account_id = silver_transactions.account_id
            and statement_totals.currency = silver_transactions.currency
            and silver_transactions.date
            between statement_totals.period_start and statement_totals.period_end
    group by
        statement_totals.user_id,
        statement_totals.account_id,
        statement_totals.currency,
        statement_totals.period_start,
        statement_totals.period_end,
        statement_totals.declared_movement

)

select
    user_id,
    account_id,
    currency,
    period_start,
    declared_movement,
    actual_movement
from actual_totals
where actual_movement != declared_movement
