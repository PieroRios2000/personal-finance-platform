---
type: decision
phase: 6
status: accepted
date: 2026-09-19
---

# ADR 0025: The savings-goal projection counts liquid savings in bank accounts only

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
- **Banco Ripley becomes the third bank**, as its own parser under the same rules as the other
  two: content detection, reconciliation against the balances the statement declares, real PDFs
  never leaving the machine ([ADR 0004](0004-real-pdfs-never-leave-your-machine.md)).
- The projection is a **separate phase** on top of gold ([Phase 6](../phases/phase-6.md)), not
  a change to the existing layers.

## Alternatives considered

- **Include the investments with a manual "current value" input**: rejected by the owner; the
  values are volatile and long-term, so they would make the answer to "when do I reach the goal"
  depend on the market instead of on saving behaviour.
- **Model only the banks already supported**: rejected, the savings account being projected is
  the Ripley one, so without it the projection would start from the wrong balance.

## Consequences

- A third parser has to be built and calibrated against real Ripley statements, using the same
  masked-dump loop as BCP and Scotiabank (each of those needed several rounds against real
  files). It is the first task of Phase 6.
- The projection reads gold. Internal transfers between the owner's own accounts have to stay
  out of income and spending ([ADR 0017](0017-internal-transfer-matching-mutual-nearest-neighbor.md)),
  otherwise moving money to the savings account would look like spending.
- Open, to settle when Phase 6 is planned: how USD accounts (Scotiabank has one) enter a goal
  set in soles, since the project has so far decided **not** to convert currencies; how the goal
  and the horizon are provided; and what the projection method is.

## Related

- [Phase 6 — savings-goal projection](../phases/phase-6.md)
- [Savings-goal projection](../concepts/savings-goal-projection.md)
- [dbt gold](../components/dbt-gold.md)
