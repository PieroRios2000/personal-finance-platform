-- silver.category_labels: the owner's own mapping from a movement's (bank,
-- description) to a category (T51, ADR 0043) -- a lookup, not a fact: no dates, no
-- amounts, replaced wholesale on every import (`lakehouse.bronze.replace_category_labels`),
-- never incrementally merged.
--
-- The bronze table only exists once a labeling file has been imported; until then this
-- is an empty table with the same columns, same pattern as investment_entries.sql, so a
-- lake with no labels yet still builds and every movement reads as 'Sin categorizar'
-- (rpt_movements.sql's own coalesce).

with source_rows as (

    {% if bronze_table_exists('category_labels') %}

        select user_id, bank, description, category, trusted, ingested_at
        from {{ source('bronze', 'category_labels') }}

    {% else %}

        select
            null::varchar as user_id,
            null::varchar as bank,
            null::varchar as description,
            null::varchar as category,
            null::boolean as trusted,
            null::timestamp with time zone as ingested_at
        where false

    {% endif %}

)

select * from source_rows
