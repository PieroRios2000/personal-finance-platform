{#
  T23: override dbt-core's own default `generate_schema_name` so a model's
  `+schema:` config becomes that schema, verbatim, instead of the default
  `<target_schema>_<custom_schema>` (e.g. gold's own models would otherwise
  land in `silver_gold`, not `gold` -- see dbt's docs on this exact,
  well-known override:
  https://docs.getdbt.com/docs/build/custom-schemas#an-alternative-pattern-for-generating-schema-names).

  Silver's own models set no `+schema:` (`custom_schema_name` is `none` for
  them), so they keep landing in `target.schema` ("silver", `profiles.yml`)
  exactly as before -- this only changes behavior for a model that opts in,
  which today is only `dbt/models/gold/**` (`dbt_project.yml`'s own
  `gold: +schema: gold`).
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
