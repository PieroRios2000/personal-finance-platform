---
type: component
phase: 3
status: in progress (T56-T59 built, rest planned)
task: T56, T57, T58, T59, T60, T61, T62, T63
---

# Spend forecast and savings goal

A per-category monthly spend forecast with honest uncertainty, and the time to reach a savings
goal the owner sets. Only T56 to T59 are built (fixed-expense detection, `make export-plan`, `make import-plan`, the forecast core and `make forecast`); the
specification is
[`docs/specs/category-forecast-and-savings-goal.md`](../../docs/specs/category-forecast-and-savings-goal.md)
and the decision is [ADR 0048](../decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md).

## Pieces

| Piece | What it does | Task |
|---|---|---|
| `forecasting/` (pure functions) | Fixed-expense detection (**built, T56**), series builder, five candidates and a trailing-median baseline, rolling-origin backtest, empirical intervals (**built, T58**), projection | T56, T58, T60 |
| `make export-plan` (**built, T56**) / `make import-plan` (**built, T57**) | The owner's workbook (`~/finance-data/plan/`): fixed-expense proposals to confirm, the dollar goal, `usd_to_pen`, the emergency settings | T56, T57 |
| Bronze `plan_fixed_items`, `plan_goal` → silver `plan_fixed_items`, `plan_goal` (**built, T57**) | The owner's confirmed plan, replaced whole on each import; empty until the first import | T57 |
| `make forecast` (**built, T59**) | Reads gold, writes the bronze forecast tables, logs ratios and counts to MLflow, builds the forecast dbt models; the projection tables join it in T60 | T59, T60 |
| Gold `fct_spend_forecast`, `rpt_category_variance`, `rpt_forecast_series_quality` (**built, T59**), `rpt_fixed_expenses` (**built, T57**), `rpt_goal_projection`, `rpt_goal_summary`, `rpt_emergency_fund` | What the dashboard reads | T57, T59, T60 |
| Superset "Forecast & goal" section | Emergency target and gap, time to goal as a range for both lines (`liquid`, `with_risk`), categories above expected, the adjust view, how far to trust each series | T61 |
| Realized-vs-backtest error chart | The monitor; joins the monthly routine | T62 |
| Recurrence as classifier features | Follow-up experiment, null result allowed | T63 |

## What T56 built

- `forecasting/fixed_expenses.py` (pure): per (bank, description, currency), a charge is a fixed
  candidate when it appears in at least 4 of the last 6 closed months and its amount is stable
  (MAD / median at most 0.10); the rest are listed as variable. Same spending definition as the
  dashboard (`flow_type = 'egreso'`, no internal transfers, no `Ingresos`).
- `forecasting/plan_file.py` (shape only, no I/O of real data): the workbook layout (`Instrucciones`
  in Spanish, `Gastos fijos`, `Meta`) and the re-export merge: the owner's `kind`, `expected_amount`
  and `Meta` values survive, untouched rows are refreshed, a row no longer detected stays with a
  note, new candidates are appended.
- `scripts/export_plan.py` reads gold in a read-only session, writes
  `~/finance-data/plan/plan-de-ahorro.xlsx` (directory 0700, file 0600, renamed over the old file
  so a crash cannot lose choices) and prints counts only.
- `numpy` is now an explicit dependency (the median and MAD); an import-linter contract keeps
  `forecasting` free of parsers, the lake and orchestration.

## What T57 built

- `forecasting/plan_import.py` (pure): `check_plan` validates the read workbook and returns the
  `Goal` or every problem at once. Messages carry the sheet, row number and field name only, never
  a typed value. Rules: `kind` is fixed, variable or ignore; `expected_amount` is a positive
  number for `fixed` (and not negative otherwise); currency PEN or USD; no repeated
  (bank, description, currency); `goal_amount`, `usd_to_pen` positive; `emergency_months` a whole
  number from 1 to 24; `emergency_basis` all or fixed_only; `target_date` after today; and
  `emergency_account` equal to an asset account's `bank` in the lake.
- `lakehouse/bronze.py`: `replace_plan` deletes the user's rows from both tables and appends the
  new plan, one `loaded_at` stamp for both (the same whole-set replace as the category labels);
  `asset_account_names` reads the accounts for the check.
- `scripts/import_plan.py` (`make import-plan`): reads the workbook (`read_plan` collects unreadable
  cells instead of stopping at the first), validates, writes nothing if there is a problem, and
  prints counts. It puts the file back to 0600 when Excel re-saved it more open.
- dbt: `silver.plan_fixed_items` and `silver.plan_goal` (empty until the first import, like the
  labels); `gold.rpt_fixed_expenses` compares each `fixed` item's `expected_amount` with the last
  six closed months' spending, with `deviation_pct` and a `status` (`as_expected`, `deviating`
  above 10 %, `not_seen`). It carries `user_id` for row-level security; its Superset dataset and
  rule come with the dashboard section (T61), since setup fails on a table Superset does not know.

## What T58 built

- `forecasting/series.py` (pure): monthly variable spending per (category, currency) over closed
  months, zero-filled from the first month with data in that currency; fixed and ignored charges
  leave the series. `Total` is the sum of the variable categories of one currency, forecast on
  its own (the fixed ones are added in the projection as their expected amount).
- `forecasting/candidates.py`: `naive_last`, `mean_3`, `median_6` (the baseline), `ses` (alpha 0.3)
  and `seasonal_naive_12`; no optimizer, so every number can be checked by hand.
- `forecasting/backtest.py`: rolling origins from 9 months of training, horizons 1-3, no
  look-ahead. A candidate replaces the baseline only if its horizon-1 MAE is at least 5 % lower
  *and* it is closer on at least 60 % of the origins. Series with fewer than 9 months or 3 nonzero
  months keep the baseline and are marked `low_history`. Intervals are the point forecast plus the
  10th/90th percentile of the model's own signed errors (floored at 0); under 12 errors they
  borrow the currency's pooled relative errors scaled by the series level, else no interval.
- Known limits: the coverage is measured on the same errors that set the interval, so it is
  optimistic; on pure noise the selection rule still switches away from the baseline in roughly
  12-27 % of series (winner's curse), which is why the 5 % margin and the win rate are both
  required.

## What T59 built

- `scripts/forecast.py` (`make forecast`): reads the monthly variable spending from gold (same
  definition as `export-plan`), drops the plan's fixed and ignored charges, runs the T58 core and
  writes two bronze Delta tables, `spend_forecasts` (kind `forecast` for horizons 1-3 and kind
  `backtest` for the one-step forecasts of closed months, with their `actual`) and
  `spend_forecast_series` (model, history, origins, `mae_rel`, `coverage`, flags). The column is
  `model_name`, not `model`, which is a reserved word for the SQL linter.
- A run is replaced by `(user_id, run_month)`; older runs stay, so the forecast made last month
  can be compared with this month's actual (T62). Running twice in a month changes nothing.
- The `Total` series is excluded from the pooled relative errors that give short series an
  interval: it is a sum of the categories already in the pool.
- MLflow gets ratios and counts only (experiment `spend-forecast`, tracking store
  `~/finance-data/mlflow.db` or `MLFLOW_TRACKING_URI`); the terminal gets counts only.
- dbt: silver `spend_forecasts`, `spend_forecast_series` (empty with the same columns until the
  first run); gold `fct_spend_forecast`, `rpt_forecast_series_quality` and `rpt_category_variance`
  (last closed month's actual against the interval of the forecast made without it:
  `above`/`within`/`below`/`no_interval`, plus how many of the last six months were above).
  All carry `user_id` for row-level security; the Superset datasets and their rules come with T61.

## How it fits

Reads closed months from gold with the dashboard's spending definition; writes only the lake
(bronze), as the categorization batch step does; dbt owns silver and gold. Currency conversion
happens only in the projection, with an owner-entered rate
([ADR 0025](../decisions/0025-savings-goal-projection-counts-liquid-savings-only.md)).

## How to verify it (once built)

`make export-plan`, edit, `make import-plan`, `make forecast`; then the dashboard section for the
demo user in a throwaway project. Acceptance criteria are in the spec, section 6.

## Related

- [Savings-goal projection](../concepts/savings-goal-projection.md)
- [Categorization](categorization.md)
- [dbt gold](dbt-gold.md)
- [Superset](superset.md)
- [Phase 6](../phases/phase-6.md)
