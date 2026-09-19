---
type: decision
phase: 6
status: accepted
date: 2026-09-19
---

# ADR 0025: The savings-goal projection counts liquid savings only, and is the one place with exchange rates

## Context

After Phase 2 the platform answers "what happened" with real statements. The owner wants it to
answer a forward question: given a savings goal and the personal cash flow the statements show,
**how long until the goal is reached**. For that, two things have to be pinned down before any
model is built: which money counts, and which banks feed it.

- The owner keeps their savings in soles at **Banco Ripley**, a bank the platform does not read
  yet (BCP and Scotiabank only).
- The owner also holds investments on other platforms, in mutual funds, for the very long term.

## Decision

- **Only liquid money in bank accounts counts** toward the goal and toward the cash flow the
  projection is built on: the accounts the platform ingests from statements (BCP, Scotiabank
  and, once added, Banco Ripley).
- **Investments elsewhere (mutual funds and similar) are out of scope, on purpose.** Their value
  moves with the market, they are held for the long term, and they have no bank statement the
  platform could ingest. They are neither an input nor part of the "amount saved".
- **Banco Ripley becomes the third source**, under the same reconciliation rules as the other
  two and the same privacy rule ([ADR 0004](0004-real-pdfs-never-leave-your-machine.md)). This ADR
  first planned a PDF parser; Ripley gives no statements, so [ADR 0027](0027-manual-excel-for-ripley-savings-and-investment-tracking.md)
  replaces that with a manual Excel.
- The projection is a **separate phase** on top of gold ([Phase 6](../phases/phase-6.md)), not
  a change to the existing layers.
- **The projection does handle exchange rates**, and it has its own **sol/dólar exchange-rate
  projection** section, so a goal can be met with dollar accounts too. This applies **only to
  the projection phase**: bronze, silver and gold keep the earlier decision of never converting
  or mixing currencies, and the projection converts on its own, on top of gold, never writing a
  converted amount back into those layers.

## Alternatives considered

- **Include the investments with a manual "current value" input**: rejected by the owner; the
  values are volatile and long-term, so they would make the answer to "when do I reach the goal"
  depend on the market instead of on saving behaviour.
- **Convert currencies in gold so every consumer gets one currency**: rejected; the owner wants
  conversion confined to the projection, and a rate is an assumption about the future, which does
  not belong in the layers that record what the bank actually said.
- **Model only the banks already supported**: rejected, the savings account being projected is
  the Ripley one, so without it the projection would start from the wrong balance.

## Consequences

- Ripley's data has to be imported and calibrated against the owner's real Excel, using the same
  masked-dump loop as BCP and Scotiabank (each of those needed several rounds against real
  data). It is the first task of Phase 6 (see ADR 0027).
- The projection reads gold. Internal transfers between the owner's own accounts have to stay
  out of income and spending ([ADR 0017](0017-internal-transfer-matching-mutual-nearest-neighbor.md)),
  otherwise moving money to the savings account would look like spending.
- The exchange rate is an input the projection has to get from somewhere and project forward;
  that is the exchange-rate section of Phase 6. Where the historical rates come from (a free
  public source, or entered by hand, since the platform is fully local and zero-cost) and how the
  future path is modelled are open, to settle when Phase 6 is planned, as are how the goal and
  the horizon are provided and what the cash-flow projection method is.

## Related

- [Phase 6 — savings-goal projection](../phases/phase-6.md)
- [Savings-goal projection](../concepts/savings-goal-projection.md)
- [dbt gold](../components/dbt-gold.md)
