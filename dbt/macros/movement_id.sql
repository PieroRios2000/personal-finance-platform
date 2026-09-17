{#
  T18b: a stable, content-based identity for one bronze.transactions row.

  bronze/transactions has no surrogate key (ADR 0006's fixed pyarrow schema
  never added one, and nothing before T18b needed one -- see
  lakehouse/bronze.py's _TRANSACTIONS_SCHEMA). internal_transfer_matches.sql
  needs one anyway, to track "this exact movement got matched" without
  reusing it for a second pair, and transactions.sql needs to recompute the
  *same* key to look a row's match status back up -- so this one hash formula
  is shared as a macro instead of hand-copied into both models, which would
  silently drift the moment one of them changed and the other didn't (every
  row would then just read as unmatched, with no error to say why).

  md5() over every bronze.transactions column except `ingested_at`, plus an
  occurrence number (T20, `occurrence_number.sql`): content identity, not
  write-time metadata, mirroring ADR 0009's own "content over file name"
  principle. `date`/`amount` are cast to varchar first -- concat_ws needs its
  arguments in a common type, and an explicit cast is clearer than relying on
  an implicit one.

  Previously known, now resolved limitation: two genuinely identical bronze
  rows (same user, account, date, amount, currency, description, source file
  -- e.g. two identical-looking small charges on the same day) used to hash to
  the same key and collapse into one for matching purposes; bronze/transactions
  has no column that could tell them apart even in principle (no PDF row/line
  number is captured anywhere in this project, still true today). T20 resolves
  it the same way it resolves the identical gap in its own business key: an
  occurrence number, scoped to one `source_file_sha256` -- see
  `occurrence_number.sql` for the full reasoning, including why it's fine that
  the specific number a given duplicate row receives isn't stable across
  separate query executions. One side effect worth knowing: `internal_transfer_matches.sql`'s
  own `tx` CTE no longer needs its `select distinct` to collapse a duplicate
  pair down to one row (movement_id is unique per bronze row now, by
  construction) -- left in place anyway as a harmless, defense-in-depth no-op;
  see that CTE's own comment and ADR 0018.
#}
{% macro movement_id(relation_alias) %}
    md5(concat_ws(
        '|',
        {{ relation_alias }}.user_id,
        {{ relation_alias }}.account_id,
        cast({{ relation_alias }}.date as varchar),
        cast({{ relation_alias }}.amount as varchar),
        {{ relation_alias }}.currency,
        {{ relation_alias }}.description,
        {{ relation_alias }}.source_file_sha256,
        cast({{ occurrence_number(relation_alias, relation_alias ~ '.description') }} as varchar)
    ))
{% endmacro %}
