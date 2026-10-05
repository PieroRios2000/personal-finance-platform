---
type: component
phase: 3
status: in progress (T56-T62 built, T63 planned)
task: T56, T57, T58, T59, T60, T61, T62, T63
---

# Spend forecast and savings goal

A per-category monthly spend forecast with honest uncertainty, and the time to reach a savings
goal the owner sets. Only T56 to T62 and T64 to T66 are built (fixed-expense detection, `make export-plan`, `make import-plan`, the forecast core, `make forecast`, the goal projection, its dashboard section and the realized-error monitor); the
specification is
[`docs/specs/category-forecast-and-savings-goal.md`](../../docs/specs/category-forecast-and-savings-goal.md)
and the decision is [ADR 0048](../decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md).

## Pieces

| Piece | What it does | Task |
|---|---|---|
| `forecasting/` (pure functions) | Fixed-expense detection (**built, T56**), series builder, five candidates and a trailing-median baseline, rolling-origin backtest, empirical intervals (**built, T58**), projection in dollars (**built, T60**) | T56, T58, T60 |
| `make export-plan` (**built, T56**) / `make import-plan` (**built, T57**) | The owner's workbook (`~/finance-data/plan/`): fixed-expense proposals to confirm, the dollar goal, `usd_to_pen`, the emergency settings | T56, T57 |
| Bronze `plan_fixed_items`, `plan_goal` → silver `plan_fixed_items`, `plan_goal` (**built, T57**) | The owner's confirmed plan, replaced whole on each import; empty until the first import | T57 |
| `make forecast` (**built, T59**) | Reads gold, writes the bronze forecast tables, logs ratios and counts to MLflow, builds the forecast dbt models; since T60 it also projects the goal (`scripts/goal_projection.py`) and builds the projection models | T59, T60 |
| Gold `fct_spend_forecast`, `rpt_category_variance`, `rpt_forecast_series_quality` (**built, T59**), `rpt_fixed_expenses` (**built, T57**), `rpt_goal_projection`, `rpt_goal_summary`, `rpt_emergency_fund`, `rpt_goal_headroom` (**built, T60**), `rpt_category_forecast` (**built, T61**), `rpt_forecast_realized` (**built, T62**) | What the dashboard reads | T57, T59, T60, T61, T62 |
| Superset "Income statement" tab | Per currency and month: income, fixed expenses, spending by category, monthly saving, planned saving and the gap to it (`rpt_income_statement`); the dashboard is split in four tabs | T66 |
| Superset "Forecast & goal" tab | Emergency target and gap, time to goal as a range for both lines (`liquid`, `with_risk`), categories above expected, the adjust view, how far to trust each series | T61 |
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
- `forecasting/backtest.py`: rolling origins from 9 months of training, forecasts 36 months ahead
  (intervals only to horizon 12, where enough origins reach it; T64), no
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
  writes two bronze Delta tables, `spend_forecasts` (kind `forecast` for horizons 1-36 and kind
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

## What T60 built

- `forecasting/projection.py`: pure functions, no I/O. The one place soles become dollars
  (`amount / usd_to_pen`); with no positive rate, or fewer than 6 months of income and no override,
  it raises `ProjectionRefused` and the run prints "goal projection skipped: <reason>" and clears
  the old rows. Never a guessed rate.
- Buckets: emergency (`Meta.emergency_account`), other liquid, risk (investments). The target is
  `emergency_months` times the monthly essential outflow (`emergency_basis` all or fixed_only).
  New savings fill the emergency gap first; only the surplus counts toward the goal.
- Two lines always: `liquid`, and `with_risk` (investments held flat at their last valuation).
  Three scenarios: base (p50 spending, median income), cautious (total p90, income p25),
  optimistic (p10, income p75). Beyond the 3 forecast months the last month is held flat; a goal
  not reached in 120 months is `NULL`, shown as "not reached".
- `scripts/goal_projection.py` runs at the end of `make forecast` from the same fits and writes
  four bronze tables (`goal_projection`, `goal_summary`, `emergency_fund`, `goal_headroom`),
  replaced as one set per user (not per run month). Silver and gold copy them
  (`rpt_goal_projection`, `rpt_goal_summary`, `rpt_emergency_fund`, `rpt_goal_headroom`), all with
  `user_id` for row-level security.
- `emergency_fund` also carries plausibility flags (essential spending above income, target above
  two years of income) and a cross-check of the liquid balance against income minus spending over
  the last 6 months (flag when more than half the months differ by over 25 % of spending).
- `goal_headroom`: per category, forecast minus the 25th percentile of the last 12 months, and its
  share of the saving gap (the "adjust" view).

## What T64-T65 built

- Forecast horizon 36 (`HORIZONS`); `INTERVAL_HORIZONS = 12`: `p10`/`p90` are `NULL` past what the
  backtest measures and `has_interval` marks the rows that have them (`fct_spend_forecast`,
  `rpt_category_forecast`). The projection holds the last measured spread and then month 36 flat.
- `rpt_forecast_realized.source`: `realized` (an older run against the month that closed) or
  `backtest` (the latest run's one-step forecast of a closed month), so the chart has rows from
  the first run.
- `make forecast` also writes `goal_cashflow` and `goal_balances` (bronze, silver, gold
  `rpt_goal_cashflow`, `rpt_goal_balances`) and gold `rpt_goal_plan`. `bi/sql/goal_dynamic.sql` is
  the Superset virtual dataset behind the goal charts: four typed native filters (goal, exchange
  rate, emergency months, horizon) change the answer with no new run; empty means the `Meta`
  value. SQL equals `forecasting.projection` (integration test); row-level security covers it.
- `rpt_goal_projection`, `rpt_goal_summary` and `rpt_emergency_fund` are still built but no
  chart reads them.

## What T66 built

- The dashboard is four tabs (Savings, Categories, Forecast & goal, Income statement) so the
  forecast is not read next to a page that mixes currencies. The typed goal filters are scoped to
  the last two tabs; Currency stays global and single-valued.
- Gold `rpt_income_statement` (ADR 0048, amendment): one row per user, currency, month and line,
  for the last 12 closed months and every month the latest run covers. `kind` is `actual`,
  `forecast` or `plan`. **Planned saving = income - expected expenses**; expected expenses are the
  plan's fixed amounts plus the median (p50) forecast of the month's total variable spending, taken
  from the latest run (its one-step backtest for a month that already closed, so closed months can
  be compared with what was planned). Income is what came in for a closed month and the base
  scenario's for a month ahead. *Saving vs plan* is monthly saving minus planned saving.
- It replaces the "Forecast: next months" table, so the per-month p10 and p90 are no longer shown
  (still in `rpt_category_forecast`); the statement shows the median only. What no category
  carries of the total is the line "~ Not split by category". The Forecast horizon filter also
  cuts the statement (`months_ahead + 1 <= horizon`).
- `make forecast` rebuilds it with the other forecast models; row-level security lists it.

## What T61 built

- Superset section "Forecast & goal" (after the investments, before the movements), authored in
  `bi/build_dashboards.py` and exported to `bi/assets`: when the goal is reached (both lines, three
  scenarios side by side), projected progress in dollars, the emergency fund with its warnings,
  where the plan has room, the next months per category (as many as the horizon filter says), categories above expected and how
  far to trust each series (the **median baseline** badge says no model beat it). A second
  Markdown note says the scenarios are not a confidence interval. The date range does not act on
  the section: it looks ahead.
- Gold `rpt_category_forecast`: the latest run only, joined to the series quality. `rpt_goal_headroom`
  names its currency column `source_currency`, so the dashboard's Currency filter does not drop
  the dollar rows of a category charged in the other currency.
- Row-level security (ADR 0036): `bi/setup_access.py` lists the six new tables; a test fails if a
  chart reads a table it does not list.
- `make demo` seeds a plan (`demo_plan`) and runs `make forecast`. The demo has eight closed months
  and the backtest needs nine, so the demo shows baselines only and an empty
  "Categories above expected" (the one chart allowed to read no rows at build).

## What T62 built

- Gold `rpt_forecast_realized`: each older `forecast` row whose month has since closed, with the
  actual (from the latest run that backtested that month), the miss, the typical miss of that same
  run's backtest in the same unit (`backtest_mae`), their ratio (`error_ratio`) and whether the
  actual fell `within`, `above` or `below` the interval. Empty until a second run exists after a
  forecast month has closed. The owner judges it; no drift test, two dozen points are too few
  (ADR 0046).
- Dashboard chart "Forecast: realized vs expected" (red where `error_ratio` > 2), allowed to read no
  rows at build; the Markdown note says it appears from the second monthly run.
- `docs/monthly-routine.md` step 4 (`export-plan` → edit → `import-plan` → `build` → `forecast`),
  checked in order by `tests/test_monthly_routine.py`; `docs/where-to-look.md` names the section's
  tables.

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
