{#
  Shared SQL implementation of `ingestion.schema.normalize_description()` (T6):
  collapse runs of 2+ padding characters (`. - _ * #`), collapse whitespace,
  trim, upper-case.

  transactions.sql's own final `description` column and its occurrence-number
  partition (T20's business key, `occurrence_number.sql`) both need the exact
  same normalized value to agree on which rows are "the same" movement -- a
  shared macro instead of writing the same two regexes twice, which would
  drift the same way `movement_id.sql`'s own docstring already warns two
  models reading the same row could silently drift apart.
#}
{% macro normalize_description(column) %}
    upper(trim(regexp_replace(
        regexp_replace({{ column }}, '[.\-_*#]{2,}', ' ', 'g'),
        '\s+', ' ', 'g'
    )))
{% endmacro %}
