-- gold.fct_investment_monthly: each investment's month, and what it returned
-- (ADR 0028).
--
-- Grain: one row per user, `place` (a fund or platform) and currency, for every
-- calendar month with at least one row in the manual Excel. Currencies and funds
-- are never mixed or converted.
--
-- A month's *gain* is the change in balance that the owner's own money does not
-- explain: closing - opening - contributions + withdrawals. Its *return* is the
-- Modified Dietz return: gain / (opening + each flow weighted by the share of
-- the month it was invested), the standard way to compare months when money
-- moves in and out during them. The month has to *close* at a `valorizacion` (its
-- last row, by date and sheet row): otherwise the closing balance is only "the
-- balance at the last movement". `return_pct` is shown only for a reliable month
-- (`is_return_reliable`); the gain and the balances are always there.
--
-- `opening_balance` is the previous month's closing balance; for the first month
-- it is the balance before its first row (a fund already worth something when the
-- records begin). If months are missing between two rows the gap is in
-- `months_since_previous` (> 1) and that month's return is not shown: it spans
-- more than a month. A first month is reliable only if its first row is an
-- `aporte` or `retiro`.

with numbered as (

    select
        *,
        row_number() over (
            partition by user_id, place, currency, month_start
            order by entry_date desc, sheet_row desc
        ) as from_the_end,
        row_number() over (
            partition by user_id, place, currency, month_start
            order by entry_date, sheet_row
        ) as from_the_start,
        case kind
            when 'aporte' then amount
            when 'retiro' then -amount
            else 0
        end as signed_flow,
        day(last_day(month_start)) as days_in_month
    from {{ ref('investment_entries') }}

),

monthly as (

    select
        user_id,
        place,
        currency,
        month_start,
        coalesce(sum(amount) filter (where kind = 'aporte'), 0) as contributions,
        coalesce(sum(amount) filter (where kind = 'retiro'), 0) as withdrawals,
        coalesce(bool_or(kind = 'valorizacion' and from_the_end = 1), false)
            as has_valuation,
        max(kind) filter (where from_the_start = 1) as first_row_kind,
        max(balance) filter (where from_the_end = 1) as closing_balance,
        max(balance - signed_flow) filter (where from_the_start = 1)
            as balance_before_first_row,
        sum(signed_flow * (days_in_month - day(entry_date)) / days_in_month)
            as weighted_flow
    from numbered
    group by user_id, place, currency, month_start

),

linked as (

    select
        *,
        lag(closing_balance) over (
            partition by user_id, place, currency order by month_start
        ) as previous_closing_balance,
        date_diff('month', lag(month_start) over (
            partition by user_id, place, currency order by month_start
        ), month_start) as months_since_previous,
        first_value(balance_before_first_row) over (
            partition by user_id, place, currency order by month_start
        ) as initial_capital
    from monthly

),

measured as (

    select
        *,
        coalesce(previous_closing_balance, balance_before_first_row)
            as opening_balance
    from linked

),

returns as (

    select
        *,
        closing_balance - opening_balance - contributions + withdrawals as gain,
        opening_balance + weighted_flow as time_weighted_capital
    from measured

),

reliable as (

    select
        *,
        -- Reliable: the month closes at a valuation, there is capital to earn a
        -- return on, and the month follows the previous one directly -- or it
        -- is the first month and a flow (not just a valuation) marks where the
        -- fund starts, since a first month of only a valuation is a 0% artifact.
        has_valuation
        and time_weighted_capital > 0
        and coalesce(
            months_since_previous = 1,
            first_row_kind in ('aporte', 'retiro')
        ) as is_return_reliable
    from returns

)

select
    user_id,
    place,
    currency,
    month_start,
    has_valuation,
    months_since_previous,
    is_return_reliable,
    opening_balance::decimal(18, 2) as opening_balance,
    contributions::decimal(18, 2) as contributions,
    withdrawals::decimal(18, 2) as withdrawals,
    closing_balance::decimal(18, 2) as closing_balance,
    gain::decimal(18, 2) as gain,
    case when is_return_reliable then gain / time_weighted_capital end as return_pct,
    (
        initial_capital
        + sum(contributions - withdrawals) over (
            partition by user_id, place, currency order by month_start
        )
    )::decimal(18, 2) as cumulative_net_contributed,
    (
        closing_balance - initial_capital
        - sum(contributions - withdrawals) over (
            partition by user_id, place, currency order by month_start
        )
    )::decimal(18, 2) as cumulative_gain
from reliable
