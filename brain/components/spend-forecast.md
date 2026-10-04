---
type: component
phase: 3
status: in progress (T56 built, rest planned)
task: T56, T57, T58, T59, T60, T61, T62, T63
---

# Spend forecast and savings goal

A per-category monthly spend forecast with honest uncertainty, and the time to reach a savings
goal the owner sets. Only T56 is built (fixed-expense detection and `make export-plan`); the
specification is
[`docs/specs/category-forecast-and-savings-goal.md`](../../docs/specs/category-forecast-and-savings-goal.md)
and the decision is [ADR 0048](../decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md).

## Pieces

| Piece | What it does | Task |
|---|---|---|
| `forecasting/` (pure functions) | Fixed-expense detection (**built, T56**), series builder, five candidates and a trailing-median baseline, rolling-origin backtest, empirical intervals, projection | T56, T58, T60 |
| `make export-plan` (**built, T56**) / `make import-plan` | The owner's workbook (`~/finance-data/plan/`): fixed-expense proposals to confirm, the dollar goal, `usd_to_pen`, the emergency settings | T56, T57 |
| `make forecast` | Reads gold, writes bronze forecast and projection tables, logs ratios and counts to MLflow, builds the new dbt models | T59 |
| Gold `fct_spend_forecast`, `rpt_category_variance`, `rpt_forecast_series_quality`, `rpt_fixed_expenses`, `rpt_goal_projection`, `rpt_goal_summary`, `rpt_emergency_fund` | What the dashboard reads | T57, T59, T60 |
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
