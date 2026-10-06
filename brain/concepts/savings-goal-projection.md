---
type: concept
phase: 6
---

# Savings-goal projection

Answering "given my cash flow, **when** do I reach my savings goal?" from the statements the
platform already ingests. Planned in [Phase 6](../phases/phase-6.md); this note fixes the
vocabulary so the model is not built on an ambiguous one.

## What the terms mean here

- **Savings** — the money sitting in the owner's bank accounts (BCP, Scotiabank, Banco Ripley).
  Three buckets since 2026-10-04: the **emergency fund** (Ripley), **other liquid** savings (the
  rest of the bank accounts) and **risk savings** (all investments), the last shown as a separate
  line of the goal ([ADR 0025](../decisions/0025-savings-goal-projection-counts-liquid-savings-only.md),
  amended).
- **Emergency target** — `emergency_months` x the monthly essential outflow, calculated from the
  owner's spending, cross-checked against income; filled before the goal.
- **Cash flow** — income minus spending per period, from `gold.fact_transactions`, using
  `flow_type` (`ingreso` / `egreso` / `pago`) and leaving out internal transfers
  (`is_internal_transfer`). A payment to a credit card is settling debt already counted as
  spending, not new spending.
- **Goal** — a target amount **in dollars** and, optionally, a date; soles are converted at the
  owner's `usd_to_pen` (soles per dollar). The projection's output is the time to
  reach it at the observed flow.

## Why it sits on gold

Gold already standardizes what the two banks print with opposite sign conventions, and already
separates real money movement from transfers between the owner's own accounts. A projection
built straight on the statements would have to rediscover both.

## Decided 2026-10-04

The method is fixed by [ADR 0048](../decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md)
and the [spec](../../docs/specs/category-forecast-and-savings-goal.md): simple models chosen by a
backtest, three scenarios instead of one number, the owner's goal as input, one owner-entered
exchange rate. Irregular months are covered by the scenarios, not weighed individually.

## Still open

- Exchange rate: the projection is the one place the project converts currencies. It needs a
  sol/dólar rate history and a projected rate path (its own section in Phase 6). Bronze, silver
  and gold stay unconverted; the conversion happens on top of gold.
- Method: a simple average of recent monthly net flow versus a forecast with uncertainty, and how
  many months of history are enough to trust either.
- Irregular months (bonuses, one-off purchases) and how they should weigh.

## Related

- [dbt gold](../components/dbt-gold.md)
- [Reconciliation](reconciliation.md)
- [ADR 0025](../decisions/0025-savings-goal-projection-counts-liquid-savings-only.md)
- [ADR 0048](../decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md)
- [Spend forecast](../components/spend-forecast.md)
