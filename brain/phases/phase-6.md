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
| Manual Excel importer | Banco Ripley gives no statements, so its savings movements (and the investments) are typed month by month into one Excel (`Ahorros` and `Inversiones` sheets). The template exists (`scripts/make_manual_templates.py`, [`docs/manual-data.md`](../../docs/manual-data.md)); the importer is designed from a masked dump of the owner's real file. [ADR 0027](../decisions/0027-manual-excel-for-ripley-savings-and-investment-tracking.md) | template, masked-description tool and the **savings import** built (`pfp import-manual`, [component](../components/manual-excel-importer.md)); the investments sheet is next |
| Investment tracking | Tyba funds and Flip: contributions, withdrawals and month-end valuations, to see each fund's return per month. Separate from the savings goal | planned, with the importer |
| Cash-flow projection | Time to reach a goal, from `gold.fact_transactions`; goals can be in soles or dollars | planned, after Ripley |
| Exchange-rate projection (sol/dólar) | A rate history and a projected rate path, so dollar balances and dollar goals can be converted. **Exists only inside this phase**: bronze, silver and gold never convert | planned, with the projection |
| Out of the goal | Investments on other platforms: long term and market-dependent, deliberately not counted toward the goal (they are tracked separately, above) | decided |

## The exchange rate stays inside this phase

Until now the project deliberately never converted currencies: every layer keeps soles and dollars
apart. The projection is the one exception, by the owner's decision
([ADR 0025](../decisions/0025-savings-goal-projection-counts-liquid-savings-only.md)): it converts
on top of gold, in its own section, and never writes a converted amount back into bronze, silver
or gold.

## What it needs from the existing platform

- Gold's `flow_type` and `is_internal_transfer`, so that moving money to the savings account is
  not read as spending. See [Savings-goal projection](../concepts/savings-goal-projection.md).
- Enough months of history per account. The monthly-continuity test in dbt already tells whether
  the months are contiguous.

## Open questions

Listed in the concept note (exchange-rate source and path model, cash-flow method, irregular months) and in the ADR. They are
settled when this phase is planned, not before.

## Related

- [Phase 2](phase-2.md) — the gold layer this reads
- [Phase 7 — alerting](phase-7.md)
