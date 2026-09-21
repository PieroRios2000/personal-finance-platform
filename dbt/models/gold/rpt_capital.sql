-- gold.rpt_capital: your total capital per currency and month, savings plus
-- investments (T35).
--
-- Grain: one row per user, currency and calendar month, from the first month any
-- account or fund has a balance. Savings is every asset account's closing balance
-- (fct_account_balance_monthly); investments is every fund's month-end balance
-- (fct_investment_monthly). A month a holding has no row keeps its last known balance
-- (an account or fund does not stop existing because its statement or its Excel row is
-- missing), so the total does not dip. A debt (a liability account) is not capital: it is
-- `debt_balance`, and `net_position` is capital minus debt. Currencies are never added
-- together.
-- Carries the same `calendar_*` columns as the other reporting tables, so the dashboard's
-- calendar filters apply to it too.
--
-- Only closed months: rows of the current month are left out
-- (`first_day_of_current_month`), so a partial month never mixes with complete ones.

with months as (

    select month_start
    from {{ ref('dim_date') }}
    group by month_start

),

holdings as (

    select
        user_id,
        currency,
        account_id as holding_id,
        'savings' as kind,
        month_start,
        closing_balance
    from {{ ref('fct_account_balance_monthly') }}
    where account_kind = 'asset'

    union all

    select
        user_id,
        currency,
        account_id as holding_id,
        'debt' as kind,
        month_start,
        closing_balance
    from {{ ref('fct_account_balance_monthly') }}
    where account_kind = 'liability'

    union all

    select
        user_id,
        currency,
        place as holding_id,
        'investments' as kind,
        month_start,
        closing_balance
    from {{ ref('fct_investment_monthly') }}

),

first_months as (

    select
        user_id,
        currency,
        holding_id,
        kind,
        min(month_start) as first_month
    from holdings
    group by user_id, currency, holding_id, kind

),

filled as (

    select
        first_months.user_id,
        first_months.currency,
        first_months.kind,
        months.month_start,
        last_value(holdings.closing_balance ignore nulls) over (
            partition by
                first_months.user_id,
                first_months.currency,
                first_months.holding_id,
                first_months.kind
            order by months.month_start
        ) as balance
    from first_months
    inner join months
        on first_months.first_month <= months.month_start
    left join holdings
        on
            first_months.user_id = holdings.user_id
            and first_months.currency = holdings.currency
            and first_months.holding_id = holdings.holding_id
            and first_months.kind = holdings.kind
            and months.month_start = holdings.month_start

),

totals as (

    select
        user_id,
        currency,
        month_start,
        coalesce(sum(balance) filter (where kind = 'savings'), 0)
            as savings_balance,
        coalesce(sum(balance) filter (where kind = 'investments'), 0)
            as investments_balance,
        coalesce(sum(balance) filter (where kind != 'debt'), 0) as total_capital,
        coalesce(sum(balance) filter (where kind = 'debt'), 0) as debt_balance,
        coalesce(sum(balance) filter (where kind != 'debt'), 0)
        - coalesce(sum(balance) filter (where kind = 'debt'), 0) as net_position
    from filled
    group by user_id, currency, month_start

)

select
    totals.*,
    calendar.year_number as calendar_year,
    calendar.year_quarter as calendar_quarter,
    calendar.month_label as calendar_month,
    calendar.month_name as calendar_month_name,
    calendar.day_name as calendar_day_name,
    -- 1 = the latest month of the data, 2 = the one before.
    dense_rank() over (order by totals.month_start desc) as month_recency
from totals
inner join {{ ref('dim_date') }} as calendar
    on totals.month_start = calendar.date
where totals.month_start < {{ first_day_of_current_month() }}
