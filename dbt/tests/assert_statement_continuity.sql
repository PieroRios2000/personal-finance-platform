-- Continuity reconciliation across statements (T16).
--
-- `ingestion/reconciliation.py` checks one statement against itself: opening
-- balance + the movements = closing balance. This is the same rule one level up,
-- between consecutive statements of the same account: a period's closing balance
-- must be the next period's opening balance, and every calendar month must have
-- its statement: the next statement must end in the month after the previous
-- one's.
--
-- The second half is about *months*, not days. Bank cycles do not tile the
-- calendar (found on real Scotiabank savings statements: one ends on the 30th
-- of a 31-day month and the next starts on the 1st) and an account can go days
-- without a movement, so counting the days between two statements would fail
-- healthy data. What matters is whether the account has a statement for each
-- month. A statement belongs to the month its period ends in.
--
-- Both halves are needed. A missing month usually shows up as a balance drift,
-- but not if that month's movements happen to net to zero; the month check
-- catches it anyway. It runs on the bronze source rather than on a silver model
-- because the rule is about which statements were ingested at all, and silver
-- adds nothing to a statement's balances.
--
-- Two statements ending in the same month also fail it (a month difference of
-- zero). That is the intended reading: a duplicated period is exactly as wrong
-- as a missing one. A bank re-download of a period with identical numbers no
-- longer gets this far (the inbox organizer files it as a duplicate, ADR 0024);
-- what still fails here is a period that really arrived twice with *different*
-- numbers, i.e. a correction to reconcile. Severity is dbt's default, `error`,
-- so a gap fails `dbt build` instead of warning.
--
-- A singular test, not a generic one: it is one query about one relation, and
-- there is nothing to parametrize.
--
-- Partitioned by currency too (T18c), not just user_id/account_id: a Scotiabank
-- statement is two independent ledgers billed as one account (ADR 0012), so it
-- writes two rows sharing account_id and period_start/period_end -- one for
-- Soles, one for Dolares. Without currency in the partition key those two
-- legitimate rows look exactly like the genuine-duplicate-period case above and
-- fail this test as a false positive; partitioning by currency as well still
-- catches a real duplicate, since a real duplicate repeats currency too.

with ordered as (

    select
        user_id,
        account_id,
        period_start,
        opening_balance,
        extract(year from period_end) * 12
        + extract(month from period_end) as month_index,
        lag(extract(year from period_end) * 12 + extract(month from period_end)) over (
            partition by user_id, account_id, currency order by period_start
        ) as previous_month_index,
        lag(closing_balance) over (
            partition by user_id, account_id, currency order by period_start
        ) as previous_closing_balance
    from {{ source('bronze', 'statements') }}

)

select
    user_id,
    account_id,
    period_start,
    month_index,
    previous_month_index,
    opening_balance,
    previous_closing_balance
from ordered
where
    previous_month_index is not null
    and (
        opening_balance != previous_closing_balance
        or month_index - previous_month_index != 1
    )
