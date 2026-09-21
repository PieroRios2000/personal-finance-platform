-- gold.fct_account_balance_monthly: an account's closing balance for each calendar
-- month, for the savings-balance chart (T32).
--
-- Grain: one row per account, currency and calendar month in which a statement ends
-- (`closing_date` is that statement's end: a statement running Jan 20 to Feb 19 is
-- February's, and a month with no statement ending in it has no row). The
-- balance is the `closing_balance` the statement declares, reconciled against its
-- movements at ingestion (ADR 0005), so it is never recomputed here. The continuity
-- test allows one statement per account and month; if a month ever had two, it
-- closes at the one that ends last. Currencies are never mixed or converted.
-- `account_kind` says what the balance is: money held (`asset`) or debt owed
-- (`liability`), so a chart can filter to savings without guessing from the bank.

with ranked as (

    select
        *,
        row_number() over (
            partition by account_id, currency, date_trunc('month', period_end)
            order by period_end desc, period_start desc
        ) as from_the_end
    from {{ source('bronze', 'statements') }}

)

select
    user_id,
    account_id,
    bank,
    account_last4,
    account_kind,
    currency,
    cast(date_trunc('month', period_end) as date) as month_start,
    period_end as closing_date,
    opening_balance,
    closing_balance,
    -- Your position: a debt is negative, so assets plus debts add up to what you have
    -- (ADR 0031). `closing_balance` stays as the statement declares it.
    case
        when account_kind = 'liability' then -closing_balance
        else closing_balance
    end as signed_closing_balance,
    -- The same for the balance the statement opens with (the first statement's is what
    -- an account already had before it was loaded): rpt_reconciliation uses it.
    case
        when account_kind = 'liability' then -opening_balance
        else opening_balance
    end as signed_opening_balance
from ranked
where from_the_end = 1
