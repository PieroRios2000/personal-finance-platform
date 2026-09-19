{#
  True if a bronze Delta table has been written at all. `delta_scan()` of a table
  that does not exist is an error, and a lake that never loaded an optional
  source (the manual Excel's investments, ADR 0028) has no such table: models on
  optional sources use this to fall back to an empty, typed result instead of
  failing every build. While dbt only parses (`execute` false) it answers true,
  so the source is still referenced and lineage is complete.
#}
{% macro bronze_table_exists(name) %}
    {% if not execute %}
        {{ return(true) }}
    {% endif %}
    {% set lake = env_var('LAKEHOUSE_URI').rstrip('/') %}
    {% set found = run_query(
        "select count(*) from glob('" ~ lake ~ "/bronze/" ~ name ~ "/_delta_log/*.json')"
    ) %}
    {{ return(found.columns[0].values()[0] > 0) }}
{% endmacro %}
