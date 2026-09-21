{#-
  The first day of the current month, as a date. The reporting tables (`rpt_*`) keep only
  rows before it: a month is closed once it is over, and the current one is partial
  (a card cycle cut mid-month, an Excel half filled), so summing it with complete months
  makes balances that do not add up. Evaluated when dbt runs, so a month closes at the
  first build after it ends.
-#}
{% macro first_day_of_current_month() %}cast(date_trunc('month', current_date) as date){% endmacro %}
