---
type: component
phase: 3
status: planned
task: T56, T57, T58, T59, T60, T61, T62, T63
---

# Spend forecast and savings goal

Planned: a per-category monthly spend forecast with honest uncertainty, and the time to reach a
savings goal the owner sets. Nothing is built; the specification is
[`docs/specs/category-forecast-and-savings-goal.md`](../../docs/specs/category-forecast-and-savings-goal.md)
and the decision is [ADR 0048](../decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md).

## Pieces (planned)

| Piece | What it does | Task |
|---|---|---|
| `forecasting/` (pure functions) | Fixed-expense detection, series builder, five candidates and a trailing-median baseline, rolling-origin backtest, empirical intervals, projection | T56, T58, T60 |
| `make export-plan` / `make import-plan` | The owner's workbook: fixed-expense proposals to confirm, the goal, the exchange rate | T56, T57 |
| `make forecast` | Reads gold, writes bronze forecast and projection tables, logs ratios and counts to MLflow, builds the new dbt models | T59 |
| Gold `fct_spend_forecast`, `rpt_category_variance`, `rpt_forecast_series_quality`, `rpt_fixed_expenses`, `rpt_goal_projection`, `rpt_goal_summary` | What the dashboard reads | T57, T59, T60 |
| Superset "Forecast & goal" section | Time to goal as a range, categories above expected, the adjust view, how far to trust each series | T61 |
| Realized-vs-backtest error chart | The monitor; joins the monthly routine | T62 |
| Recurrence as classifier features | Follow-up experiment, null result allowed | T63 |

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
