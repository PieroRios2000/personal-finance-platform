-- gold.rpt_forecast_series_quality: how far to trust each forecast series (T59, ADR 0048,
-- spec 3.2). One row per user, `run_month`, category and currency, straight from the run:
-- the selected model, months of history, backtest origins, `mae_rel` (the model's error
-- relative to the median baseline, 1.0 = no better), the interval `coverage` and the
-- flags `baseline_used` and `low_history`.
--
-- The coverage is measured on the same errors the interval came from, so it is
-- optimistic. Carries `user_id` for row-level security (ADR 0036); not monthly, so no
-- `calendar_*` columns.

select
    user_id,
    run_month,
    category,
    currency,
    model_name,
    baseline_used,
    low_history,
    n_months,
    n_origins,
    mae_rel,
    coverage
from {{ ref('spend_forecast_series') }}
