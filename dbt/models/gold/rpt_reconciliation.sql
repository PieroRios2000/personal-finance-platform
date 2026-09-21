-- gold.rpt_reconciliation: per account and currency, does its balance add up? (T36)
--
-- The identity every account must satisfy over the closed months loaded:
--
--     opening balance of the first statement + movements up to the last closed
--     statement = closing balance of that statement
--
-- `difference` is the closing balance minus (opening + movements); it is 0 when every
-- movement was read, none twice. It is the check that tells a missing or duplicated
-- movement apart from a balance that simply started above zero. All amounts are your
-- position (a debt is negative, ADR 0031), so an account and a card are on the same
-- scale. Only closed months (`first_day_of_current_month`), and the movements are those
-- up to the last closed statement's closing date, so a statement of the current month
-- and the days after it are not part of it. Currencies are never added together.
-- Per account, not per month: the dashboard's calendar filters do not apply to it.

with closed as (

    select *
    from {{ ref('fct_account_balance_monthly') }}
    where month_start < {{ first_day_of_current_month() }}

),

bounds as (

    select
        user_id,
        account_id,
        currency,
        min(month_start) as first_month,
        max(month_start) as last_month
    from closed
    group by user_id, account_id, currency

),

first_statement as (

    select
        bounds.user_id,
        bounds.account_id,
        bounds.currency,
        closed.signed_opening_balance as opening_balance
    from bounds
    inner join closed
        on
            bounds.user_id = closed.user_id
            and bounds.account_id = closed.account_id
            and bounds.currency = closed.currency
            and bounds.first_month = closed.month_start

),

last_statement as (

    select
        bounds.user_id,
        bounds.account_id,
        bounds.currency,
        bounds.first_month,
        bounds.last_month,
        closed.bank,
        closed.account_last4,
        closed.account_kind,
        closed.closing_date,
        closed.signed_closing_balance as closing_balance
    from bounds
    inner join closed
        on
            bounds.user_id = closed.user_id
            and bounds.account_id = closed.account_id
            and bounds.currency = closed.currency
            and bounds.last_month = closed.month_start

),

movements as (

    select
        last_statement.account_id,
        last_statement.currency,
        sum(facts.signed_amount) as net_movements
    from last_statement
    inner join {{ ref('fact_transactions') }} as facts
        on
            last_statement.account_id = facts.account_id
            and last_statement.currency = facts.currency
            and last_statement.closing_date >= facts.date
    group by last_statement.account_id, last_statement.currency

)

select
    last_statement.user_id,
    last_statement.account_id,
    last_statement.bank,
    last_statement.account_last4,
    last_statement.account_kind,
    last_statement.currency,
    last_statement.first_month,
    last_statement.last_month,
    first_statement.opening_balance,
    last_statement.closing_balance,
    coalesce(movements.net_movements, 0) as net_movements,
    last_statement.closing_balance
    - coalesce(movements.net_movements, 0)
    - first_statement.opening_balance as difference
from last_statement
inner join first_statement
    on
        last_statement.user_id = first_statement.user_id
        and last_statement.account_id = first_statement.account_id
        and last_statement.currency = first_statement.currency
left join movements
    on
        last_statement.account_id = movements.account_id
        and last_statement.currency = movements.currency
