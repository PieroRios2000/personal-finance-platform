-- gold.rpt_income_statement: the monthly income statement (T66, ADR 0048): per currency,
-- income, spending (fixed, then by category), the saving and the saving that was planned,
-- for the last 12 closed months and every month the forecast covers.
--
-- Grain: one row per user, currency, month and `line`. `line` carries its own order as a
-- numeric prefix ("1 · Income" ... "8 · Saving vs plan"), so a pivot sorted by it reads
-- as a statement. `kind` says where the number comes from: `actual` (what happened in a
-- closed month), `forecast` (a month ahead: the base scenario's income, the plan's fixed
-- expenses and the forecast's median) or `plan` (the expected expenses and the planned
-- saving, which exist for closed and open months alike).
--
-- Definitions. Spending is `flow_type = 'egreso' AND NOT is_internal_transfer` (ADR 0031);
-- income is `flow_type = 'ingreso' AND NOT is_internal_transfer`; an outflow labelled
-- 'Ingresos' is shown as 'Sin categorizar', as the Categories charts do. "Fixed" are the
-- plan's `kind = 'fixed'` charges; everything else is shown by category. Months ahead
-- have the forecast's median (p50) by category, and the part of the series' total that no
-- category carries as "~ Not split by category" (the total is forecast on its own).
--
-- Planned saving = income - expected expenses. Expected expenses = the plan's fixed
-- amounts + the median forecast of the month's total variable spending, from the latest
-- run: the one-step backtest for a month that already closed, the forecast for one
-- ahead. Income is what really came in for a closed month and the base scenario's for a
-- month ahead, so "Saving vs plan" (saving - planned saving) isolates how the spending
-- did against its forecast. Charges the plan calls `ignore` are not forecast, so they
-- show as spending without a counterpart.
--
-- Closed months only (`rpt_movements` leaves the open month out); the open month and
-- later are always `forecast`/`plan`. Carries `user_id` for row-level security (ADR 0036).
-- Not a calendar table: no `calendar_*` columns, the calendar filters do not apply.

-- `kind`, `line` and `variable` are the readable names of this table's columns; the rule
-- against keyword-like identifiers is switched off for the whole file.
-- noqa: disable=RF04

{% set past_months = 12 %}

with plan_fixed as (

    select
        user_id,
        currency,
        sum(expected_amount) as expected_fixed
    from {{ ref('plan_fixed_items') }}
    where kind = 'fixed'
    group by user_id, currency

),

fixed_items as (

    select
        user_id,
        bank,
        description,
        currency
    from {{ ref('plan_fixed_items') }}
    where kind = 'fixed'

),

latest_run as (

    select
        user_id,
        max(run_month) as run_month
    from {{ ref('fct_spend_forecast') }}
    group by user_id

),

forecast as (

    select
        fct_spend_forecast.user_id,
        fct_spend_forecast.currency,
        fct_spend_forecast.category,
        fct_spend_forecast.target_month as month,
        fct_spend_forecast.p50
    from {{ ref('fct_spend_forecast') }}
    inner join latest_run
        on
            fct_spend_forecast.user_id = latest_run.user_id
            and fct_spend_forecast.run_month = latest_run.run_month
    where
        fct_spend_forecast.target_month
        >= cast(
            {{ first_day_of_current_month() }} - interval {{ past_months }} month
            as date
        )

),

forecast_total as (

    select
        user_id,
        currency,
        month,
        p50
    from forecast
    where category = 'Total'

),

forecast_by_category as (

    select
        user_id,
        currency,
        category,
        month,
        p50
    from forecast
    where
        category <> 'Total'
        and month >= {{ first_day_of_current_month() }}

),

base_income as (

    select
        user_id,
        currency,
        month,
        income
    from {{ ref('rpt_goal_cashflow') }}
    where scenario = 'base'

),

movements as (

    select
        rpt_movements.user_id,
        rpt_movements.currency,
        rpt_movements.flow_type,
        rpt_movements.signed_amount,
        cast(date_trunc('month', rpt_movements.date) as date) as month,
        fixed_items.description is not null as is_fixed,
        case
            when rpt_movements.category = 'Ingresos' then 'Sin categorizar'
            else rpt_movements.category
        end as category
    from {{ ref('rpt_movements') }}
    left join fixed_items
        on
            rpt_movements.user_id = fixed_items.user_id
            and rpt_movements.bank = fixed_items.bank
            and rpt_movements.description = fixed_items.description
            and rpt_movements.currency = fixed_items.currency
    where
        not rpt_movements.is_internal_transfer
        and rpt_movements.flow_type in ('ingreso', 'egreso')
        and rpt_movements.date
        >= cast(
            {{ first_day_of_current_month() }} - interval {{ past_months }} month
            as date
        )

),

actual_totals as (

    select
        user_id,
        currency,
        month,
        coalesce(sum(signed_amount) filter (where flow_type = 'ingreso'), 0) as income,
        coalesce(
            sum(-signed_amount) filter (where flow_type = 'egreso' and is_fixed), 0
        ) as fixed,
        coalesce(
            sum(-signed_amount) filter (where flow_type = 'egreso' and not is_fixed), 0
        ) as variable
    from movements
    group by user_id, currency, month

),

actual_categories as (

    select
        user_id,
        currency,
        category,
        month,
        sum(-signed_amount) as amount
    from movements
    where flow_type = 'egreso' and not is_fixed
    group by user_id, currency, category, month

),

-- One row per month with the numbers behind every line: what happened for a closed
-- month, what is expected for one ahead.
months as (

    select
        user_id,
        currency,
        month,
        'actual' as kind,
        income,
        fixed,
        variable
    from actual_totals

    union all

    select
        forecast_total.user_id,
        forecast_total.currency,
        forecast_total.month,
        'forecast' as kind,
        base_income.income,
        coalesce(plan_fixed.expected_fixed, 0) as fixed,
        forecast_total.p50 as variable
    from forecast_total
    left join base_income
        on
            forecast_total.user_id = base_income.user_id
            and forecast_total.currency = base_income.currency
            and forecast_total.month = base_income.month
    left join plan_fixed
        on
            forecast_total.user_id = plan_fixed.user_id
            and forecast_total.currency = plan_fixed.currency
    where forecast_total.month >= {{ first_day_of_current_month() }}

),

expected as (

    select
        months.*,
        coalesce(plan_fixed.expected_fixed, 0) + forecast_total.p50
            as expected_expenses
    from months
    left join plan_fixed
        on
            months.user_id = plan_fixed.user_id
            and months.currency = plan_fixed.currency
    left join forecast_total
        on
            months.user_id = forecast_total.user_id
            and months.currency = forecast_total.currency
            and months.month = forecast_total.month

),

split as (

    select
        user_id,
        currency,
        month,
        sum(p50) as p50
    from forecast_by_category
    group by user_id, currency, month

),

lines as (

    select
        user_id,
        currency,
        month,
        kind,
        '1 · Income' as line,
        income as amount
    from expected
    where income is not null

    union all

    select
        user_id,
        currency,
        month,
        kind,
        '2 · Fixed expenses' as line,
        fixed as amount
    from expected
    where fixed <> 0

    union all

    select
        user_id,
        currency,
        month,
        'actual' as kind,
        '3 · ' || category as line,
        amount
    from actual_categories

    union all

    select
        user_id,
        currency,
        month,
        'forecast' as kind,
        '3 · ' || category as line,
        p50 as amount
    from forecast_by_category

    union all

    select
        forecast_total.user_id,
        forecast_total.currency,
        forecast_total.month,
        'forecast' as kind,
        '3 · ~ Not split by category' as line,
        forecast_total.p50 - coalesce(split.p50, 0) as amount
    from forecast_total
    left join split
        on
            forecast_total.user_id = split.user_id
            and forecast_total.currency = split.currency
            and forecast_total.month = split.month
    where
        forecast_total.month >= {{ first_day_of_current_month() }}
        and forecast_total.p50 - coalesce(split.p50, 0) <> 0

    union all

    select
        user_id,
        currency,
        month,
        kind,
        '4 · Total expenses' as line,
        fixed + variable as amount
    from expected

    union all

    select
        user_id,
        currency,
        month,
        kind,
        '5 · Monthly saving' as line,
        income - fixed - variable as amount
    from expected
    where income is not null

    union all

    select
        user_id,
        currency,
        month,
        'plan' as kind,
        '6 · Expected expenses' as line,
        expected_expenses as amount
    from expected
    where expected_expenses is not null

    union all

    select
        user_id,
        currency,
        month,
        'plan' as kind,
        '7 · Planned saving' as line,
        income - expected_expenses as amount
    from expected
    where income is not null and expected_expenses is not null

    union all

    select
        user_id,
        currency,
        month,
        'actual' as kind,
        '8 · Saving vs plan' as line,
        expected_expenses - fixed - variable as amount
    from expected
    where
        kind = 'actual'
        and income is not null
        and expected_expenses is not null

)

select
    user_id,
    currency,
    month,
    strftime(month, '%Y-%m')
    || case
        when month >= {{ first_day_of_current_month() }} then ' (forecast)'
        else ''
    end as month_label,
    (
        extract(year from month) * 12 + extract(month from month)
        - extract(year from {{ first_day_of_current_month() }}) * 12
        - extract(month from {{ first_day_of_current_month() }})
    )::integer as months_ahead,
    kind,
    line,
    cast(amount as decimal(18, 2)) as amount
from lines
