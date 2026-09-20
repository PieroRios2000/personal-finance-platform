-- silver.investment_entries: the manual Excel's investment rows (ADR 0027, 0028),
-- typed and with the month they belong to.
--
-- One row per contribution (`aporte`), withdrawal (`retiro`) or month-end
-- valuation (`valorizacion`) of a fund or platform (`place`), in one currency.
-- Deliberately not part of `silver.transactions`: an investment is not spending
-- or income, its balance moves with the market, and it never counts toward the
-- savings goal or the liquid cash flow (ADR 0025).
--
-- The bronze table only exists once an investments sheet has been loaded; until
-- then this is an empty table with the same columns, so a lake with no
-- investments still builds (`bronze_table_exists`).

with source_rows as (

    {% if bronze_table_exists('investment_entries') %}

        select
            user_id,
            place,
            currency,
            entry_date,
            date_trunc('month', entry_date)::date as month_start,
            kind,
            amount,
            balance,
            detail,
            sheet_row,
            month_key,
            ingested_at
        from {{ source('bronze', 'investment_entries') }}

    {% else %}

        select
            null::varchar as user_id,
            null::varchar as place,
            null::varchar as currency,
            null::date as entry_date,
            null::date as month_start,
            null::varchar as kind,
            null::decimal(18, 2) as amount,
            null::decimal(18, 2) as balance,
            null::varchar as detail,
            null::integer as sheet_row,
            null::varchar as month_key,
            null::timestamp with time zone as ingested_at
        where false

    {% endif %}

)

select * from source_rows
