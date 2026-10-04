-- gold.rpt_fixed_expenses: each expense the owner confirmed as fixed, against what was
-- really charged in the last closed months (T57, ADR 0048, spec 4.1).
--
-- Grain: one row per user, bank, description and currency of the plan's `kind = 'fixed'`
-- items. `expected_amount` is the owner's; the actual is the month's spending on that
-- exact (bank, description) in that currency (ADR 0031: expenses that are not internal
-- transfers, `sum(-signed_amount)`), over the last six closed months only -- the open
-- month never counts (`first_day_of_current_month`).
--
-- `last_observed_month` is the latest of those months with a charge and
-- `last_observed_amount` its total. `deviation_pct` is how far that amount sits from the
-- expected one; above 10 % either way the `status` is 'deviating', so a price rise is
-- noticed. An item with no charge in the window is 'not_seen' (it may have been
-- cancelled, or the description changed); nothing is guessed for it.
--
-- Carries `user_id` for row-level security (ADR 0036). Not monthly, so it has no
-- `calendar_*` columns: the calendar filters do not apply to it.

{% set window_months = 6 %}
{% set deviation_threshold_pct = 10 %}

with fixed_items as (

    select *
    from {{ ref('plan_fixed_items') }}
    where kind = 'fixed'

),

monthly_spend as (

    select
        user_id,
        bank,
        description,
        currency,
        cast(date_trunc('month', date) as date) as month_start,
        sum(-signed_amount) as amount
    from {{ ref('fact_transactions') }}
    where
        flow_type = 'egreso'
        and not is_internal_transfer
        and date < {{ first_day_of_current_month() }}
        and date >= cast(
            date_trunc('month', current_date) - interval {{ window_months }} month
            as date
        )
    group by user_id, bank, description, currency, month_start

),

observed as (

    select
        user_id,
        bank,
        description,
        currency,
        count(*) as months_seen_last_6,
        max(month_start) as last_observed_month,
        arg_max(amount, month_start) as last_observed_amount
    from monthly_spend
    group by user_id, bank, description, currency

),

compared as (

    select
        fixed_items.user_id,
        fixed_items.bank,
        fixed_items.description,
        fixed_items.currency,
        fixed_items.category,
        fixed_items.expected_amount,
        coalesce(observed.months_seen_last_6, 0) as months_seen_last_6,
        observed.last_observed_month,
        observed.last_observed_amount,
        round(
            (observed.last_observed_amount - fixed_items.expected_amount)
            * 100.0 / fixed_items.expected_amount,
            1
        ) as deviation_pct,
        fixed_items.loaded_at as plan_loaded_at
    from fixed_items
    left join observed
        on
            fixed_items.user_id = observed.user_id
            and fixed_items.bank = observed.bank
            and fixed_items.description = observed.description
            and fixed_items.currency = observed.currency

)

select
    *,
    case
        when deviation_pct is null then 'not_seen'
        when abs(deviation_pct) > {{ deviation_threshold_pct }} then 'deviating'
        else 'as_expected'
    end as status
from compared
