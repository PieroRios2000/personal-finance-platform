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
    closing_balance
from ranked
where from_the_end = 1
