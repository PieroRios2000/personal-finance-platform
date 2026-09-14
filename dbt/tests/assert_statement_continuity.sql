-- Continuity reconciliation across statements (T16).
--
-- `ingestion/reconciliation.py` checks one statement against itself: opening
-- balance + the movements = closing balance. This is the same rule one level up,
-- between consecutive statements of the same account: a period's closing balance
-- must be the next period's opening balance, and the next period must start the
-- day after the previous one ended.
--
-- Both halves are needed. A missing month usually shows up as a balance drift,
-- but not if that month's movements happen to net to zero; the date check catches
-- it anyway. It runs on the bronze source rather than on a silver model because
-- the rule is about which statements were ingested at all, and silver adds
-- nothing to a statement's balances.
--
-- A singular test, not a generic one: it is one query about one relation, and
-- there is nothing to parametrize. Severity is dbt's default, `error`, so a gap
-- fails `dbt build` instead of warning.

with ordered as (

    select
        user_id,
        account_id,
        period_start,
        opening_balance,
        lag(period_end) over (
            partition by user_id, account_id order by period_start
        ) as previous_period_end,
        lag(closing_balance) over (
            partition by user_id, account_id order by period_start
        ) as previous_closing_balance
    from {{ source('bronze', 'statements') }}

)

select
    user_id,
    account_id,
    period_start,
    previous_period_end,
    opening_balance,
    previous_closing_balance
from ordered
where
    previous_period_end is not null
    and (
        opening_balance != previous_closing_balance
        or date_diff('day', previous_period_end, period_start) != 1
    )
