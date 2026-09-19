---
type: phase
phase: 6
status: planned
---

# Phase 6 — Savings-goal projection (planned)

Answer, from the owner's real cash flow, **how long it takes to reach a savings goal**. Nothing
here is built; this note records what was decided and what is still open, so the next planning
session starts from facts. Scope decision:
[ADR 0025](../decisions/0025-savings-goal-projection-counts-liquid-savings-only.md).

## Scope

| Piece | What | Status |
|---|---|---|
| Banco Ripley parser | A third bank: the owner's savings account, in soles. Same rules as BCP and Scotiabank: content detection, reconciliation against declared balances, masked layout dump reviewed by the owner before any parser work | planned, first task |
| Projection | Time to reach a goal, from `gold.fact_transactions` | planned, after Ripley |
| Out of scope | Investments on other platforms (mutual funds): long term and market-dependent, deliberately not counted | decided |

## What it needs from the existing platform

- Gold's `flow_type` and `is_internal_transfer`, so that moving money to the savings account is
  not read as spending. See [Savings-goal projection](../concepts/savings-goal-projection.md).
- Enough months of history per account. The monthly-continuity test in dbt already tells whether
  the months are contiguous.

## Open questions

Listed in the concept note (currencies, method, irregular months) and in the ADR. They are
settled when this phase is planned, not before.

## Related

- [Phase 2](phase-2.md) — the gold layer this reads
- [Phase 7 — alerting](phase-7.md)
