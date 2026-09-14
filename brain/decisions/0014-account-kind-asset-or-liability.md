---
type: decision
phase: 1
status: accepted
date: 2026-09-14
---

# ADR 0014: `account_kind` (`asset`/`liability`) on `Statement`, joined into silver

## Context

T18b needs to match a real transfer between two accounts of the same user (e.g. paying a
Scotiabank credit card from a BCP checking account) and never count it as income or expense.
Piero flagged the subtlety when T18b was scoped, before any of its matching logic was written:

- A **checking → checking** transfer is opposite-signed on both sides — money leaves one
  account (negative) and arrives in the other (positive).
- A **checking → credit-card payment** is the *same* sign on both sides — BCP records the
  payment as a negative outflow (money left the checking account), and Scotiabank records the
  same payment as a negative debt-reduction (`ingestion/parsers/scotiabank.py`'s `_money()`:
  a trailing `-` reduces debt owed). Both parsers already document this: BCP's `amount` is
  money on hand (negative = charge, positive = credit); Scotiabank's is debt owed (negative =
  payment, positive = charge) — the opposite convention, because the two balances represent
  opposite *kinds* of thing, an asset versus a liability.

T18b's sign-matching logic cannot tell these two cases apart without knowing what kind of
account each side of a candidate transfer is. That knowledge has to live somewhere before T18b
can be built, which is what this task (T18a) adds.

## Decision

- **A new field, `account_kind: Literal["asset", "liability"]`, on `Statement`.** Exactly two
  values, because Phase 1 only has two kinds of account (a checking account whose balance is
  money on hand, and a credit card whose balance is debt owed) and nothing about T18b's
  sign-matching needs a finer distinction. Follows `Currency`'s existing pattern in
  `ingestion/schema.py`: a module-level `Literal` type alias, used as the field's annotation and
  exported for parsers and tests to reuse.

- **Hardcoded per parser, not read from the PDF.** `ingestion/parsers/bcp.py` sets
  `account_kind="asset"` on every `Statement` it builds; `ingestion/parsers/scotiabank.py` sets
  `account_kind="liability"` on every one of the (possibly several, one per currency) statements
  it returns. A bank's product type doesn't vary per statement — BCP is always a checking
  account, Scotiabank is always a credit card, for every PDF either parser will ever see — so
  this is a constant each parser already "knows" about itself, the same way it already hardcodes
  `bank="BCP"` or `bank="Scotiabank"` on every `Statement` it builds. Nothing about parsing a
  specific PDF's content decides it.

- **On `Statement`, not `Transaction`.** An account's kind doesn't vary per movement any more
  than its opening/closing balance does — `opening_balance` and `closing_balance` already live
  only on `Statement`, and `account_kind` follows the same reasoning. Putting it on `Transaction`
  instead would mean repeating the exact same value on every row of every statement for no
  reason, and — closer to why it matters here — it would suggest, wrongly, that a single
  transaction's "kind" is something that could vary independently of the account it belongs to.
  It can't: it's a property of the account, fixed by which bank/product issued it.

- **Carried into `silver.transactions` by joining `bronze.statements` on `account_id`, not by
  duplicating it into every `bronze.transactions` row.** `bronze/transactions` has no
  balance/kind concept at all today (see `lakehouse/bronze.py`'s two separate pyarrow schemas),
  and writing `account_kind` onto every transaction row bronze-side would be exactly the
  redundant repetition the previous point rejects, just moved one layer down instead of avoided.
  `dbt/models/silver/transactions.sql` instead does:

  ```sql
  with account_kinds as (
      select account_id, max(account_kind) as account_kind
      from {{ source('bronze', 'statements') }}
      group by account_id
  )
  select ..., account_kinds.account_kind, ...
  from {{ source('bronze', 'transactions') }} as bronze_transactions
  left join account_kinds
      on bronze_transactions.account_id = account_kinds.account_id
  ```

  **Why `account_id` alone, not `account_id` + `source_file_sha256`/`file_sha256`.** A single
  account accumulates one `bronze.statements` row per ingested period, and — the case that
  actually forced this choice — Scotiabank's own parser can write *two* `Statement` rows for the
  very same file (one per currency, same `account_id`, same `file_sha256`; see
  `ingestion/parsers/scotiabank.py`'s module docstring). Joining on `account_id` +
  `source_file_sha256` would still let a transaction match more than one `bronze.statements`
  row whenever that happened, fanning every one of that file's transactions out into duplicate
  rows in silver — a real double-counting bug, not a hypothetical one, since it is exactly what
  T18's own fixture already produces. Joining on `account_id` alone has the same problem in the
  more common case (many periods per account), so **`account_kinds` groups by `account_id` and
  takes `max(account_kind)` before the join**, collapsing however many `bronze.statements` rows
  a given account has down to exactly one. This makes the join's cardinality safe by
  construction — a transaction matches at most one row of `account_kinds`, full stop — rather
  than relying on every future statement for that account happening to agree, or on nobody ever
  writing a Scotiabank-shaped file that produces more than one statement row per key.
  `max()` doesn't arbitrate a genuine disagreement here: `account_kind` is a per-parser constant
  keyed off the bank baked into `account_id`'s own HMAC (ADR 0005), so in practice every
  `bronze.statements` row for one `account_id` already agrees, and `max()` exists only to make
  that agreement load-bearing for the join's shape instead of assumed.
  `tests/test_dbt_silver_integration.py`'s
  `test_silver_carries_account_kind_without_duplicating_rows` writes three periods for one
  account and asserts exactly three rows come back, not nine — the regression this guards
  against.

  **`left join`, not `inner join`.** A transaction whose account somehow has no matching
  `bronze.statements` row should never silently disappear from silver — that would be exactly
  the kind of silent data loss this project's reconciliation checks exist to prevent (see
  `ingestion/reconciliation.py`'s and `bcp.py`'s own "fails loudly, never silently" language).
  A `left join` keeps the row and lets `account_kind` come back `null` instead; the model's
  `not_null` data test on that column (`dbt/models/silver/schema.yml`) then turns that into a
  loud `dbt build` failure rather than a row nobody notices went missing.

## Alternatives considered

- **A dbt-side lookup, e.g. `case when bank = 'BCP' then 'asset' when bank = 'Scotiabank' then
  'liability' end`.** Explicitly rejected by Piero when this was scoped. It works today only
  because each bank currently offers exactly one product in this project — the moment a bank
  offers *both* a checking account and a credit card (not unusual for a real bank), a
  `bank`-keyed lookup can no longer tell them apart, and every downstream query using it goes
  quietly wrong for that bank's rows. The real distinguishing fact is which *product*, not which
  *bank*, issued the statement — the account itself already knows this at parse time (a parser
  module is written for one specific product), so hardcoding it there, once, is strictly more
  honest than re-deriving a fact from a proxy (bank name) that only inconsistently implies it.
- **`account_kind` on `Transaction`.** Rejected: an account's kind doesn't vary per movement,
  exactly like `opening_balance`/`closing_balance` don't — see the Decision section. Would also
  have meant writing it into `bronze/transactions`' pyarrow schema and every future parser's
  per-row construction, for a value that's identical across every row of a statement anyway.
- **Duplicate `account_kind` into every `bronze.transactions` row at write time** (in
  `lakehouse/bronze.py`, from the `Statement` its transactions belong to), instead of joining in
  dbt. Rejected: `bronze/transactions` is explicitly the table with no balance/kind concept
  (see `lakehouse/bronze.py`'s two separate schemas for `transactions` and `statements`), and
  bronze is append-only and long-lived — baking a value that's really a property of the account
  into every historical row multiplies storage and, worse, means a future correction to a
  parser's hardcoded `account_kind` would require a full bronze backfill (ADR 0010) to fix rows
  that a one-line dbt model change would otherwise fix for free on the next `dbt build`.
- **`inner join` instead of `left join`** in `silver/transactions.sql`. Rejected: silently
  dropping a transaction because its account has no matching statement row is a worse failure
  mode than surfacing it loudly. The `not_null` test on `account_kind` gets the same "never
  silent" property an `inner join` would, without the risk of a row disappearing unnoticed.
- **A finer-grained kind** (e.g. `checking`, `savings`, `credit_card`) instead of the two-value
  `asset`/`liability`. Rejected as speculative: nothing in this project, including T18b, needs
  to distinguish a savings account from a checking one — both are assets for sign-matching
  purposes. `asset`/`liability` is the coarsest distinction that is actually load-bearing today;
  a finer one can be added later without disturbing this one, the same way `Currency` only ever
  grew the two values this project actually handles.

## Consequences

- T18b can now write `case when a.account_kind = b.account_kind then ... else ... end`-shaped
  sign logic instead of guessing from `bank`, and its own `tasks/todo.md` entry has been updated
  to say so explicitly (added in this same PR).
- `Statement.account_kind` is required with no default: every existing direct `Statement(...)`
  construction across the test suite (bronze, reconciliation, benchmark and integration tests,
  besides the two real parsers) needed a value added. All of them use `"asset"`, matching their
  BCP-shaped fixtures.
- Adding a required, non-nullable column to `bronze/statements`' fixed pyarrow schema
  (`lakehouse/bronze.py`) means any *pre-existing* real Delta table written before this change
  would need a schema-evolving write (or a backfill) before a new `write_statement()` call could
  append to it cleanly under the current `mode="append"` — not exercised by this PR (no real
  bronze table exists in CI, and this hasn't been run against Piero's real lake yet), flagged as
  a pending item in `tasks/todo.md` for Piero to confirm on his own machine.
- `silver.transactions` gains one more join. Cheap in practice (`bronze.statements` is orders of
  magnitude smaller than `bronze.transactions`, and the join key is indexed by nothing more
  exotic than equality on a string), and it keeps `bronze/transactions` exactly as narrow as
  ADR 0006's fixed-schema reasoning already wants it to be.

## Related

- [BCP parser](../components/bcp-parser.md) — sets `account_kind="asset"`.
- [Scotiabank parser](../components/scotiabank-parser.md) — sets `account_kind="liability"`,
  including the multi-statement-per-file case this ADR's join has to stay safe against.
- [Lakehouse](../components/lakehouse.md) — `bronze/statements`' schema, where the column lands.
- [dbt silver](../components/dbt-silver.md) — the join this ADR specifies, in `silver.transactions`.
- [ADR 0005: Transaction schema with user and account](0005-transaction-schema-with-user-and-account.md) —
  `account_id`'s own HMAC, which `account_kind` is keyed off transitively (through `bank`).
- [ADR 0006: Lake location by URI](0006-lake-location-by-uri.md) — the fixed pyarrow schema
  pattern `account_kind` follows in `bronze/statements`.
- [ADR 0010: A backfill replaces a file's rows](0010-bronze-backfill-replaces-not-versions.md) —
  why duplicating `account_kind` into bronze rows was rejected.
- [ADR 0011: `delta_scan()` as a dbt source](0011-delta-scan-as-a-dbt-source.md) — the source
  declarations `account_kinds`' CTE reads from.
- [Reconciliation](../concepts/reconciliation.md) — the "fail loudly, not silently" principle
  behind the `left join` + `not_null` choice.
- [Phase 1](../phases/phase-1.md)
