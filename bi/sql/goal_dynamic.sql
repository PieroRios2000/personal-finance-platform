{#- The dynamic goal (T65, ADR 0048): the Superset virtual dataset behind "Goal: when you
reach it", "projected progress" and "Emergency fund". It recombines the monthly pieces
of the projection (`gold.rpt_goal_cashflow`, `gold.rpt_goal_balances`) under the goal, the
exchange rate and the emergency months that the dashboard's native filters hold, and falls
back to the `Meta` values (`gold.rpt_goal_plan`) while a filter is empty. It must give the
answer of `forecasting.projection` for the same inputs (tests/test_dbt_goal_dynamic_*).

The native filters are typed free values. `filter_values(..., remove_filter=True)` reads
them here and keeps Superset from also adding them as a WHERE on the result. A value
reaches the SQL only as a number: commas are dropped, then it must be digits with at most
one dot and at most 1e12, or it is ignored. No comments inside the SQL itself. -#}
{%- macro typed(column) -%}
{%- set values = filter_values(column, remove_filter=True) -%}
{%- set text = ((values[0] if values else '') | string).replace(',', '').strip() -%}
{%- if text and text.isascii() and text.replace('.', '', 1).isdigit() and text | length <= 15 and text | float <= 1000000000000 -%}
{{ text | float }}
{%- else -%}
null
{%- endif -%}
{%- endmacro -%}
with params as (
    select
        plan.user_id,
        plan.target_date,
        coalesce({{ typed('goal_amount_usd') }}, plan.goal_amount) as goal_amount_usd,
        coalesce(nullif({{ typed('usd_to_pen') }}, 0), plan.usd_to_pen) as usd_to_pen,
        coalesce({{ typed('emergency_months') }}, plan.emergency_months) as emergency_months,
        coalesce({{ typed('horizon_months') }}, plan.horizon_months) as horizon_months
    from gold.rpt_goal_plan as plan
),

held as (
    select
        params.user_id,
        balances.bucket,
        balances.run_month,
        case balances.currency
            when 'USD' then balances.amount
            when 'PEN' then balances.amount / params.usd_to_pen
        end as usd
    from gold.rpt_goal_balances as balances
    inner join params on balances.user_id = params.user_id
),

start as (
    select
        held.user_id,
        max(held.run_month) as run_month,
        coalesce(sum(held.usd) filter (where held.bucket = 'emergency'), 0) as emergency_now,
        coalesce(sum(held.usd) filter (where held.bucket = 'other_liquid'), 0) as other_liquid,
        coalesce(sum(held.usd) filter (where held.bucket = 'risk'), 0) as risk,
        coalesce(sum(held.usd) filter (where held.bucket = 'essential'), 0) as essential
    from held
    group by held.user_id
),

sized as (
    select
        start.*,
        params.target_date,
        params.emergency_months * start.essential as emergency_target
    from start
    inner join params on start.user_id = params.user_id
),

monthly as (
    select
        flow.user_id,
        flow.scenario,
        flow.month_index,
        flow.month,
        sum(
            case flow.currency
                when 'USD' then flow.income
                when 'PEN' then flow.income / params.usd_to_pen
            end
        ) as income,
        sum(
            case flow.currency
                when 'USD' then flow.income - flow.fixed - flow.variable
                when 'PEN' then (flow.income - flow.fixed - flow.variable) / params.usd_to_pen
            end
        ) as saving
    from gold.rpt_goal_cashflow as flow
    inner join params on flow.user_id = params.user_id
    group by flow.user_id, flow.scenario, flow.month_index, flow.month
),

scenarios as (
    select
        user_id,
        scenario,
        avg(saving) filter (where month_index <= 3) as projected_monthly_saving,
        max(income) filter (where month_index = 1) as income
    from monthly
    group by user_id, scenario
),

cumulative as (
    select
        user_id,
        scenario,
        month_index,
        month,
        sum(saving) over (partition by user_id, scenario order by month_index) as saved
    from monthly
    union all
    select
        scenarios.user_id,
        scenarios.scenario,
        0 as month_index,
        sized.run_month as month,
        0.0 as saved
    from scenarios
    inner join sized on scenarios.user_id = sized.user_id
),

lines as (
    select 'liquid' as line
    union all
    select 'with_risk' as line
),

path as (
    select
        cumulative.user_id,
        cumulative.scenario,
        lines.line,
        cumulative.month_index,
        cumulative.month,
        sized.emergency_now + cumulative.saved - sized.emergency_target as spare,
        least(
            greatest(sized.emergency_now + cumulative.saved, 0), sized.emergency_target
        ) as emergency,
        case lines.line
            when 'liquid' then sized.other_liquid
            else sized.other_liquid + sized.risk
        end + greatest(0, sized.emergency_now + cumulative.saved - sized.emergency_target) as goal_progress
    from cumulative
    cross join lines
    inner join sized on cumulative.user_id = sized.user_id
),

reached as (
    select
        path.*,
        min(path.month_index) filter (
            where path.goal_progress >= params.goal_amount_usd - 0.000000001
        ) over (partition by path.user_id, path.scenario, path.line) as months_to_goal,
        min(path.month) filter (
            where path.goal_progress >= params.goal_amount_usd - 0.000000001
        ) over (partition by path.user_id, path.scenario, path.line) as reached_month,
        min(path.month_index) filter (
            where path.spare >= -0.000000001
        ) over (partition by path.user_id, path.scenario, path.line) as months_to_fill
    from path
    inner join params on path.user_id = params.user_id
),

needed as (
    select
        sized.user_id,
        lines.line,
        (
            (date_part('year', sized.target_date) - date_part('year', sized.run_month)) * 12
            + date_part('month', sized.target_date) - date_part('month', sized.run_month)
        ) as months_left,
        case lines.line
            when 'liquid' then sized.other_liquid
            else sized.other_liquid + sized.risk
        end as counted
    from sized
    cross join lines
)

select
    reached.user_id,
    reached.scenario,
    reached.line,
    reached.month_index,
    reached.month,
    reached.emergency,
    reached.goal_progress,
    reached.months_to_goal,
    reached.reached_month,
    scenarios.projected_monthly_saving,
    case
        when needed.months_left is null or needed.months_left < 1 then null
        when params.goal_amount_usd - needed.counted <= 0 then 0.0
        else greatest(
            0,
            (
                sized.emergency_target + params.goal_amount_usd - needed.counted
                - sized.emergency_now
            ) / needed.months_left
        )
    end as required_monthly_saving,
    sized.emergency_target,
    sized.emergency_now,
    greatest(0, sized.emergency_target - sized.emergency_now) as emergency_gap,
    reached.months_to_fill,
    case when sized.essential > 0 then sized.emergency_now / sized.essential end as months_covered,
    case when scenarios.income > 0 then sized.emergency_target / scenarios.income end as months_of_income,
    sized.essential > scenarios.income as essential_over_income,
    sized.emergency_target > 24 * scenarios.income as target_over_two_years_income,
    params.goal_amount_usd,
    params.usd_to_pen,
    params.emergency_months,
    params.horizon_months,
    checks.balance_mismatch,
    checks.mismatch_months,
    checks.months_checked
from reached
inner join params on reached.user_id = params.user_id
inner join sized on reached.user_id = sized.user_id
inner join scenarios on reached.user_id = scenarios.user_id and reached.scenario = scenarios.scenario
inner join needed on reached.user_id = needed.user_id and reached.line = needed.line
left join gold.rpt_emergency_fund as checks
    on reached.user_id = checks.user_id and reached.scenario = checks.scenario
