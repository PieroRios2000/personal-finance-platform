-- silver.category_predictions: the trained model's own guess for a movement's
-- (bank, description), batch-computed at ingest (T54, ADR 0045) -- never the
-- owner's confirmed answer (that's silver.category_labels). A lookup, not a fact,
-- replaced wholesale by scripts.categorize_new_movements on every ingest.
-- `category` is already categorization.model.suggest's own output -- the model's
-- prediction above its calibrated confidence threshold, the rules-based guesser's
-- below it -- so there is no separate confidence column here.
--
-- The bronze table only exists once a model has been trained and at least one
-- ingest has run since; until then this is an empty table with the same columns,
-- same pattern as category_labels.sql, so a lake with no predictions yet still
-- builds and gold.rpt_movements falls through to the owner's label, then
-- 'Sin categorizar' (its own coalesce).

with source_rows as (

    {% if bronze_table_exists('category_predictions') %}

        select user_id, bank, description, category, predicted_at
        from {{ source('bronze', 'category_predictions') }}

    {% else %}

        select
            null::varchar as user_id,
            null::varchar as bank,
            null::varchar as description,
            null::varchar as category,
            null::timestamp with time zone as predicted_at
        where false

    {% endif %}

)

select * from source_rows
