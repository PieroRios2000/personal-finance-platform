---
type: decision
phase: 2
status: accepted
date: 2026-09-20
---

# ADR 0031: `signed_amount`, the effect of a movement on you, the same on every bank

## Context

`amount` keeps each bank's own sign ([ADR 0015](0015-account-kind-asset-or-liability.md)): on BCP money
out is negative; on a Scotiabank credit card a charge is **positive** (the debt grows) and a payment
is **negative** (the debt shrinks). That is right for reconciling against the statement, but on a
dashboard the owner reads a card charge of 250 as money in and a payment of 300 as money out, the
opposite of what happened to their position.

## Decision

`gold.fact_transactions` gets a second measure, `signed_amount`: what the movement does to your
position, **the same on every bank**. Money in and debt paid down are positive; money out and new debt
are negative. For an asset account it equals `amount`; for a liability (`account_kind = 'liability'`)
it is `-amount`.

- `amount` stays as the statement prints it, so a movement still matches the PDF and the reconciliation
  and continuity tests are untouched.
- `flow_type` is unchanged (ingreso / egreso / pago); `signed_amount` and `flow_type` agree: an
  `egreso` is always negative, an `ingreso` positive, a `pago` (debt paid down) positive.
- The dashboard's Movements table shows both, and colours by `signed_amount` (green improves your
  position, red worsens it). The cash flow chart and the summary cards are unchanged: they already
  used the absolute value with `flow_type`.
- A liability's *balance* is still the debt owed (positive) in `closing_balance`; the savings-balance
  chart only shows asset accounts.

## Alternatives considered

- **Flip `amount` for liabilities in silver:** would make movements stop matching the statement and
  break the reconciliation tests (ADR 0005, 0015). Rejected: the raw sign is evidence.
- **Only fix it in the BI tool:** every consumer (Superset, the future models, a notebook) would
  redo it. One column in gold is the single definition.

## Related

[ADR 0015](0015-account-kind-asset-or-liability.md), [ADR 0020](0020-gold-star-schema-flow-type-and-dim-account-grain.md)
(`flow_type`), [ADR 0030](0030-superset-for-dashboards-over-the-read-only-role.md).

## Update 2026-09-20: every chart uses it, transfers count, debt is negative

The owner asked that the dashboard show what really came in and went out:

- **Cash flow and the summary cards read `signed_amount`**, not `flow_type` with the absolute value.
  Money in is the sum of the positive `signed_amount`, money out the sum of the negative ones.
- **Movements between your own accounts count on both sides** (out of one account, in to the other),
  no longer excluded. The two sides do not always match (a fee between banks, an exchange difference),
  and that difference now shows in the net. `is_internal_transfer` stays as a filter for whoever wants
  them left out. This supersedes the "no internal transfers" wording of the T32 charts.
- **Debt is negative in balances too:** `fct_account_balance_monthly.signed_closing_balance` is
  `-closing_balance` for a liability. The balance chart and the "net position" card add every account,
  so assets plus debts is what you have; `closing_balance` stays as the statement prints it.
- `flow_type` and the Flow type filter are unchanged; only the sums stopped depending on them.
