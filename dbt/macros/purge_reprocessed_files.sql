{#
  T20: before transactions.sql's own incremental MERGE runs, delete every
  existing silver.transactions row belonging to a `source_file_sha256` that
  has new data in this run.

  A plain MERGE on `unique_key` alone can insert a row whose key is new and
  update a row whose key already matches, but it can never delete a target
  row whose key no longer appears anywhere in this run's own source data --
  and that is exactly what a `pfp backfill` (ADR 0010) needs when a parser
  fix changes a row's own description, and so its business key: the *old*
  row, under its *old* key, would otherwise sit in silver forever, orphaned,
  next to the corrected row under its new key. Purging first, scoped to only
  the files this run actually touches, makes that case correct by
  construction instead of something the MERGE itself would have to be taught
  (DuckDB's own MERGE has no per-partition "WHEN NOT MATCHED BY SOURCE"
  equivalent that could safely scope a delete to one file without also
  matching every *other* file's unrelated, currently-correct rows).

  "Has new data in this run" reuses transactions.sql's own incremental
  filter, unmodified: a bronze row whose `(source_file_sha256, ingested_at)`
  pair isn't already present in `{{ this }}`. Every row `pfp ingest` or
  `pfp backfill` (ADR 0010) writes for one file shares that file's own single
  `ingested_at` (`lakehouse/bronze.py`'s `write_statement()` stamps it once
  per call, not once per row), so this is always an all-or-nothing purge of
  one file's *entire* previous silver slice, never a partial one -- exactly
  matching how bronze itself only ever replaces a file's rows wholesale, never
  a subset of them.

  A *different* file producing the exact same business key (e.g. a bank
  regenerating a statement PDF with different bytes for the same period) is
  deliberately left alone here: its `source_file_sha256` was never in silver
  before, so there's nothing of *its own* to purge, and the MERGE's own
  `WHEN MATCHED` branch (matching on the business key, not the file) is what
  correctly updates that row in place instead. See transactions.sql's own
  docstring and ADR 0018 for the two cases side by side.

  One more case: a file that bronze no longer has *any* transaction for (a
  manual-Excel month corrected so it has only a balance marker, ADR 0027,
  or a file removed from bronze). It has no fresh row to select above, so its
  old silver rows would stay forever; silver rows whose `source_file_sha256`
  is no longer in bronze at all are purged too, so silver never keeps a
  movement bronze has dropped.

  A first run, or `dbt build --full-refresh` (`is_incremental()` false in
  both): nothing to purge, the target is being rebuilt from scratch anyway.
#}
{% macro purge_reprocessed_files() %}
{% if is_incremental() %}
    delete from {{ this }}
    where source_file_sha256 not in (
        select distinct source_file_sha256
        from {{ source('bronze', 'transactions') }}
    )
    or source_file_sha256 in (
        select distinct bronze_transactions.source_file_sha256
        from {{ source('bronze', 'transactions') }} as bronze_transactions
        where not exists (
            select 1
            from {{ this }} as already_in_silver
            where
                already_in_silver.source_file_sha256 = bronze_transactions.source_file_sha256
                and already_in_silver.ingested_at = bronze_transactions.ingested_at
        )
    )
{% endif %}
{% endmacro %}
