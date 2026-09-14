---
type: decision
phase: 1
status: accepted
date: 2026-09-14
---

# ADR 0016: `currency` on `Statement`, and a currency-aware continuity partition

## Context

T18c was found by Piero actually running `dbt build` against synthetic BCP + dual-currency
Scotiabank data — the first time anyone had (T17's own synthetic seeding never included
Scotiabank, so nothing had exercised this combination through `dbt build` before). It failed:

```
[ERROR]: in test assert_statement_continuity (tests/assert_statement_continuity.sql)
  Got 1 result, configured to fail if != 0
```

**Root cause.** A Scotiabank credit-card statement carries two currencies (Soles and Dólares)
as two independent, separately-reconciled ledgers (ADR 0012), so `ingestion/parsers/
scotiabank.py`'s `parse()` returns one `Statement` per currency that has activity —
`lakehouse/bronze.py` then writes one `bronze.statements` row per `Statement`, so a single real
statement lands as **two** rows sharing `account_id` and `period_start`/`period_end`.

`dbt/tests/assert_statement_continuity.sql`'s own header comment documents an intended check:
"two statements covering the same period" is exactly as wrong as a missing one (a bank
regenerating a PDF with different bytes gets past T7's file-level dedup). Its `lag() over
(partition by user_id, account_id order by period_start)` window functions have no way to tell
that case apart from Scotiabank's two same-period, different-currency rows — both look like "a
second row starting on the same day the first one starts, whose opening balance doesn't match
the first one's closing balance." The check is doing exactly what it was built to do; it just
has no currency signal to rule this legitimate case out. `Statement` had no `currency` field to
give it one — only `Transaction` did.

## Decision

**`currency: Currency` on `Statement`, mirroring `account_kind`'s own precedent (ADR 0015)
exactly:**

- **Required, no default; hardcoded per parser, not read from the PDF.** `ingestion/parsers/
  bcp.py` sets `currency="PEN"` on the one `Statement` it ever builds — confirmed from the
  parser's own module docstring ("a BCP account statement covers one account in one currency")
  and reconfirmed here rather than assumed: nothing in `bcp.py` reads a currency off the page at
  all, every `Transaction` it builds is already hardcoded to `"PEN"`. If BCP is ever found to
  handle USD statements too, this hardcoded value — and the module docstring's own claim — would
  both need revisiting; nothing in this PR's own testing suggests that's the case today.
  `ingestion/parsers/scotiabank.py` already loops `for currency in _CURRENCIES:` building one
  `Statement` per currency with activity — it now sets `currency=currency` from that same loop
  variable, not a constant, since (unlike BCP) a single parser run produces both values.
- **On `Statement`, not only `Transaction`.** The same reasoning `account_kind` already
  established for itself: a statement period's currency doesn't vary per movement any more than
  its `opening_balance`/`closing_balance` do, and — the concrete reason it's load-bearing here —
  the continuity test operates on `bronze.statements`, not `bronze.transactions`, so it needs the
  fact at the same grain it already reads everything else at.
- **A new cross-field check**, extending `Statement`'s existing `_validate_consistency`
  (previously: every transaction must share the statement's `user_id`/`bank`/`account_id`) to
  also require `transaction.currency == statement.currency`. This isn't asked for by T18c's
  acceptance criteria directly, but it's a small, mechanical extension of a check the model
  already runs, and it makes load-bearing (rather than merely asserted in a docstring) the exact
  invariant the rest of this decision depends on: "each Scotiabank `Statement` only ever holds
  transactions in its own currency." Without it, a future bug that built a mismatched `Statement`
  would silently produce bronze rows the continuity test partitions one way and
  `silver.transactions` reads another way, with nothing catching the disagreement.

**`lakehouse/bronze.py`'s `_STATEMENTS_SCHEMA` gains a `currency` column**, following
`account_kind`'s own fixed-pyarrow-schema pattern (ADR 0006) for the same
`SchemaMismatchError`-avoidance reasons documented at the top of that module.

**`assert_statement_continuity.sql`'s two `lag()` window functions partition by
`user_id, account_id, currency` instead of `user_id, account_id`.** This is the actual fix: it
gives the test exactly the signal it was missing to tell "two legitimate same-period rows, one
per currency" apart from "the same currency's period duplicated." A genuine duplicate (same
account, same currency, same period) still fails, because it still shares every column in the
now-wider partition key — the fix narrows the false positive without touching the real check's
logic at all, just what it's allowed to consider "the same series."

**`dbt/models/sources.yml`'s `bronze.statements` description** documents the new column and why
the continuity test partitions by it, the same way `account_kind`'s own addition was documented
there.

**`currency` is *not* joined into `silver.transactions`.** T18c's own prompt asked this to be a
judgment call, so the reasoning gets a full section below.

## Should `Statement.currency` flow into `silver.transactions`? No — it's redundant by
## construction, and now enforced, not just asserted

`silver/transactions.sql` already carries `bronze_transactions.currency` straight through from
`bronze.transactions` — `Transaction` has had its own `currency` field since T6 (ADR 0005), long
before this task, and `dbt/models/silver/schema.yml` already runs `not_null` and
`accepted_values(["PEN", "USD"])` on it. The question this ADR actually has to answer is whether
`Statement.currency` needs its *own* path into silver (an `account_kinds`-shaped join, or a
column comparison), the way `account_kind` needed one because `Transaction` had no equivalent
field of its own to fall back on.

**It doesn't, and adding one would be pure duplication:**

- **The two can never disagree, by construction.** Every `Transaction` a parser builds already
  gets the same `currency` as the `Statement` it belongs to — trivially true for BCP (everything
  is `"PEN"`), and true for Scotiabank because `transactions_by_currency[currency]` only ever
  feeds the `Statement` built for that same `currency` inside the same loop iteration (see
  `ingestion/parsers/scotiabank.py`'s `parse()`). This ADR's own new cross-field check on
  `Statement` (above) makes that agreement a validation-time guarantee, not just an
  implementation detail nobody checks: a `Statement`/`Transaction` currency mismatch can no
  longer reach bronze at all, so there is nothing for a `silver.transactions` join to catch that
  the model layer hasn't already ruled out one level earlier.
- **`account_kind` needed the join because `Transaction` had no field to carry the fact at all.**
  `currency` is the opposite case: `Transaction` already has its own, already reaches silver, and
  is already tested there. Joining `Statement.currency` in on top would add a second column that
  is guaranteed equal to the first one on every row, for every account, forever — exactly the
  "no columns that nothing asked for" rule `dbt-silver.md`'s own design notes already hold silver
  to, and exactly the kind of speculative surface CLAUDE.md's "simplest thing that meets the
  criteria" asks agents to avoid.
- **The `account_kinds`-style join exists to solve a cardinality problem `currency` doesn't have
  in the same way.** `account_kind` needed `group by account_id, max(account_kind)` specifically
  *because* Scotiabank's one-account-many-currencies shape would otherwise fan a transaction's
  row out into duplicates when joining `bronze.statements` on `account_id` alone. `currency`
  can't hit that problem from the transactions side at all — `bronze.transactions` already
  carries its own `currency` per row, with no join and no fan-out risk, because it was never
  missing the field to begin with.

If a future task ever needs `Statement`-level currency facts in silver that `Transaction`
doesn't already carry on its own (none is foreseen today), the `account_kinds` CTE pattern this
ADR's `account_kind` precedent already established is what to reach for — the reasoning above is
about this field, not a rule against ever joining `bronze.statements` into silver again.

## Alternatives considered

- **Infer currency in the continuity test from something other than a new column** — e.g.
  matching Scotiabank's two rows by `declared_charges_total`/`opening_balance` proximity, or
  excluding Scotiabank by `bank = 'Scotiabank'`. Rejected for the same reason ADR 0015 rejected a
  `bank`-keyed lookup for `account_kind`: it only works today because Scotiabank is the one bank
  with this shape. A `bank`-keyed special case bakes in "Scotiabank is the multi-currency one"
  instead of the real, general fact ("two rows with different currencies for the same period are
  not a duplicate"), and breaks the moment BCP or a future bank ever needs the same handling.
- **A finer partition than `currency`** — e.g. also including something to distinguish
  hypothetical same-account-same-currency-same-period *legitimate* splits. Rejected as
  speculative: nothing in this project produces that shape, and ADR 0012's own reasoning already
  establishes currency as the one axis Scotiabank actually splits statements on.
- **Joining `Statement.currency` into `silver.transactions`** — see the dedicated section above.
- **Skipping the new `Transaction`/`Statement` currency cross-check.** Considered, since T18c's
  acceptance criteria don't explicitly ask for it. Kept anyway: it is a three-line extension of a
  validator the model already runs (not a new abstraction), and it is precisely what makes this
  ADR's central "no join needed" argument a guarantee instead of an assumption. Documented here
  rather than left implicit, per this task's own request to explain the call.

## Consequences

- `Statement.currency` is required with no default: every existing direct `Statement(...)`
  construction across the test suite (bronze, reconciliation, benchmark and integration tests,
  besides the two real parsers) needed a value added, the same ripple ADR 0015 caused for
  `account_kind`. All of them use `"PEN"`, matching their BCP-shaped fixtures.
- Adding a required, non-nullable column to `bronze/statements`' fixed pyarrow schema
  (`lakehouse/bronze.py`) means any *pre-existing* real Delta table written before this change
  would need a schema-evolving write (or a backfill) before a new `write_statement()` call could
  append to it cleanly under the current `mode="append"` — not exercised by this PR (no real
  bronze table exists in CI), flagged as a pending item in `tasks/todo.md` for Piero to confirm
  on his own machine, the same caveat ADR 0015 already flagged for `account_kind`.
- `tests/test_dbt_silver_integration.py`'s `_write()` helper gained `bank`/`account_id`/
  `account_kind`/`currency` override parameters (previously hardcoded to the shared BCP fixture),
  needed to seed a same-period Scotiabank dual-currency pair for this task's own verification
  test without duplicating the whole helper.
- Verified live against an isolated local SeaweedFS instance (`docker compose -p pfp-poc-t18c`,
  a distinct project name and host port from the `pfp-poc` instance already running under another
  session, left untouched): the new false-positive test reproduced the exact reported failure
  (`Got 1 result, configured to fail if != 0`) before this ADR's SQL fix, and passed after it; a
  genuine same-account/same-currency/same-period duplicate still fails both before and after.

## Related

- [BCP parser](../components/bcp-parser.md) — sets `currency="PEN"`.
- [Scotiabank parser](../components/scotiabank-parser.md) — sets each statement's own currency
  from its per-currency loop, including the multi-statement-per-file case this ADR's partition
  fix has to stay safe against.
- [Lakehouse](../components/lakehouse.md) — `bronze/statements`' schema, where the column lands.
- [dbt silver](../components/dbt-silver.md) — the continuity test this ADR fixes, and why
  `currency` is deliberately *not* joined into `silver.transactions`.
- [ADR 0005: Transaction schema with user and account](0005-transaction-schema-with-user-and-account.md) —
  `Transaction.currency`'s own origin, which this ADR's cross-check now enforces `Statement`
  agrees with.
- [ADR 0006: Lake location by URI](0006-lake-location-by-uri.md) — the fixed pyarrow schema
  pattern `currency` follows in `bronze/statements`.
- [ADR 0011: `delta_scan()` as a dbt source](0011-delta-scan-as-a-dbt-source.md) — the source
  declaration the continuity test reads from.
- [ADR 0012: Scotiabank password-fallback detection](0012-scotiabank-password-fallback-detection.md) —
  the one-statement-per-currency design this whole ADR is downstream of.
- [ADR 0015: `account_kind` (asset/liability)](0015-account-kind-asset-or-liability.md) — the
  precedent this ADR follows field-for-field, and the join pattern this ADR explains why
  `currency` does *not* need to repeat.
- [Reconciliation](../concepts/reconciliation.md) — the "fail loudly, not silently" principle
  behind the new cross-field currency check.
- [Phase 1](../phases/phase-1.md)
