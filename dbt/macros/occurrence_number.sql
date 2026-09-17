{#
  T20: disambiguates two-or-more bronze.transactions rows that would otherwise
  share one identity slot -- e.g. two rows that are genuinely byte-identical
  (movement_id.sql's own use, T18b), or two rows whose *normalized*
  description happens to coincide (transactions.sql's own business key, T20).
  A `row_number()`, scoped to one `source_file_sha256`: two identical-looking
  rows in the *same* PDF get different numbers, so both survive as separate
  rows; the same-looking row re-appearing in a *different* file (e.g. a bank
  regenerating a PDF for the same period) is deliberately left free to
  collide with whatever's already there under a different occurrence slot --
  see [Business key](../../brain/concepts/business-key.md) for why that's the
  intended reading, not a bug.

  `description_expr` is the caller's own description expression, not a fixed
  column name, because the two callers need two different partitions:
  `movement_id.sql` disambiguates *raw* bronze rows (nothing else about its
  own identity changes), while `transactions.sql`'s business key
  disambiguates the *normalized* description (two statements' differently
  padded or cased renderings of the same movement must still collide). One
  shared mechanism, two different partitions -- never the same one, so this
  macro takes the expression instead of assuming a column name.

  No PDF row/line number is captured anywhere in this project (movement_id.sql's
  own docstring already said so, and T20 doesn't change that), so `order by`
  can't reconstruct two rows' real position in the PDF -- it doesn't need to.
  When every column in the partition is genuinely identical between two rows,
  they are interchangeable in every way this project can observe them, so it
  is immaterial which one DuckDB's `row_number()` happens to label "1" versus
  "2"; nothing downstream depends on that label surviving between two
  separate query executions (see transactions.sql's own docstring for why its
  incremental MERGE never needs it to).
#}
{% macro occurrence_number(relation_alias, description_expr) %}
    row_number() over (
        partition by
            {{ relation_alias }}.source_file_sha256,
            {{ relation_alias }}.user_id,
            {{ relation_alias }}.account_id,
            {{ relation_alias }}.date,
            {{ relation_alias }}.amount,
            {{ relation_alias }}.currency,
            {{ description_expr }}
        order by
            {{ relation_alias }}.source_file_sha256,
            {{ relation_alias }}.user_id,
            {{ relation_alias }}.account_id,
            {{ relation_alias }}.date,
            {{ relation_alias }}.amount,
            {{ relation_alias }}.currency,
            {{ description_expr }}
    )
{% endmacro %}
