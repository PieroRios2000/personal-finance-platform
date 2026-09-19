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
  Investments held elsewhere (mutual funds) are **not** savings for this purpose
  ([ADR 0025](../decisions/0025-savings-goal-projection-counts-liquid-savings-only.md)).
- **Cash flow** — income minus spending per period, from `gold.fact_transactions`, using
  `flow_type` (`ingreso` / `egreso` / `pago`) and leaving out internal transfers
  (`is_internal_transfer`). A payment to a credit card is settling debt already counted as
  spending, not new spending.
- **Goal** — a target amount (in soles or in dollars) and, optionally, a date. The projection's output is the time to
  reach it at the observed flow.

## Why it sits on gold

Gold already standardizes what the two banks print with opposite sign conventions, and already
separates real money movement from transfers between the owner's own accounts. A projection
built straight on the statements would have to rediscover both.

## Open questions

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
