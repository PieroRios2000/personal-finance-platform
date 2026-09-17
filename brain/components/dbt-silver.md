---
type: component
phase: 1
status: built
task: T16, T18a, T18b, T18c, T20
---

# dbt silver

A dbt-duckdb project that reads bronze's Delta tables straight off S3 with DuckDB's
`delta_scan()` and builds `silver.transactions`, with the tests that say what silver is
allowed to contain — including continuity between statement periods, which nothing before T16
checked. Design decisions in [ADR 0011](../decisions/0011-delta-scan-as-a-dbt-source.md).

## Pieces

| Piece | What it does |
|---|---|
| [`dbt/profiles.yml`](../../dbt/profiles.yml) | The DuckDB connection: on-disk database (`PFP_DUCKDB_PATH`, default `dbt/pfp.duckdb`), schema `silver`, the `httpfs` and `delta` extensions, and the `TYPE s3 / PROVIDER config` secret that lets DuckDB reach SeaweedFS (`ENDPOINT`, `URL_STYLE 'path'`, `USE_SSL false`). Every value comes from the same `.env` variables `lakehouse/storage.py` reads |
| [`dbt/models/sources.yml`](../../dbt/models/sources.yml) | `bronze.transactions` and `bronze.statements`, declared as one `external_location` f-string: `delta_scan('<LAKEHOUSE_URI>/bronze/{name}')` |
| [`dbt/models/silver/transactions.sql`](../../dbt/models/silver/transactions.sql) | `silver.transactions`: bronze's columns with the description re-normalized, plus `account_kind` joined in from `bronze.statements` (T18a), `is_internal_transfer` joined in from `internal_transfer_matches` (T18b), and `occurrence_number` (T20). Incremental (`materialized='incremental'`, `incremental_strategy='merge'`), keyed on the business key — see "Incremental MERGE" below |
| [`dbt/macros/occurrence_number.sql`](../../dbt/macros/occurrence_number.sql) | T20: a `row_number()`, scoped to one `source_file_sha256`, that disambiguates two otherwise-identical bronze rows — shared by `movement_id.sql` (raw description) and `transactions.sql`'s own business key (normalized description) |
| [`dbt/macros/purge_reprocessed_files.sql`](../../dbt/macros/purge_reprocessed_files.sql) | T20: `transactions.sql`'s `pre_hook` — deletes a run's touched files' *existing* silver rows before the `MERGE` inserts their fresh ones, so a `pfp backfill` that changes a row's own business key doesn't orphan the old one |
| [`dbt/macros/normalize_description.sql`](../../dbt/macros/normalize_description.sql) | T20: SQL port of `ingestion.schema.normalize_description()`, shared by `transactions.sql`'s own `description` column and its business-key partition, so the two can't drift apart |
| [`dbt/models/silver/internal_transfer_matches.sql`](../../dbt/models/silver/internal_transfer_matches.sql) | T18b: one row per `bronze.transactions` row, with whether it's a plausible transfer candidate and, if matched, which other movement it paired with. The single shared computation the two models below and `transactions.sql`'s flag all build on -- see ADR 0017 for the full matching algorithm |
| [`dbt/models/silver/internal_transfers.sql`](../../dbt/models/silver/internal_transfers.sql) | T18b: `silver.internal_transfers`, one row per matched pair (both legs' own details, `day_diff`, `amount_diff`) |
| [`dbt/models/silver/unmatched_transfers.sql`](../../dbt/models/silver/unmatched_transfers.sql) | T18b: `silver.unmatched_transfers`, transfer candidates with no mutual match -- for review, never dropped |
| [`dbt/macros/movement_id.sql`](../../dbt/macros/movement_id.sql) | T18b: a content-based identity (md5 hash) for one `bronze.transactions` row, shared by `internal_transfer_matches.sql` and `transactions.sql` so their two lookups of the same row can never silently drift apart. Extended in T20 to include `occurrence_number`, resolving a limitation it used to document as its own out-of-scope gap |
| [`dbt/models/silver/schema.yml`](../../dbt/models/silver/schema.yml) | `not_null` on every column, `accepted_values` on `currency` (`PEN`, `USD`) and `account_kind` (`asset`, `liability`), matching `ingestion.schema.Currency`/`AccountKind`; column docs and tests for the T18b and T20 models too |
| [`dbt/tests/assert_statement_continuity.sql`](../../dbt/tests/assert_statement_continuity.sql) | The continuity test: a period's closing balance is the next period's opening balance, and the periods are contiguous, per user, account and currency (T18c) |
| [`dbt/tests/assert_internal_transfers_are_one_to_one.sql`](../../dbt/tests/assert_internal_transfers_are_one_to_one.sql) | T18b: standing proof that no movement appears in more than one matched pair |
| [`dbt/tests/assert_statement_balance_reconciliation.sql`](../../dbt/tests/assert_statement_balance_reconciliation.sql) | T20: re-checks T8's own Python-level balance check at the model layer — per account/period/currency, `sum(silver.transactions.amount)` equals the matching statement's `closing_balance - opening_balance` — specifically to catch what the incremental `MERGE` could get wrong that a check upstream of it never would |
| [`dbt/tests/assert_transactions_business_key_is_unique.sql`](../../dbt/tests/assert_transactions_business_key_is_unique.sql) | T20: standing proof the `MERGE`'s own `unique_key` is actually unique — dbt's merge strategy doesn't refuse a duplicate-keyed source batch itself, it just matches ambiguously |
| `[tool.sqlfluff.*]` in [`pyproject.toml`](../../pyproject.toml) | sqlfluff with the **dbt** templater and the `duckdb` dialect, so the linter sees the `delta_scan(...)` expression dbt actually compiles |

## What silver adds, and what it deliberately does not

- **No casts.** Bronze writes with one fixed pyarrow schema (ADR 0006) and `delta_scan()` hands
  those types to DuckDB unchanged: `date` is `DATE`, `amount` is `DECIMAL(18, 2)`,
  `ingested_at` is `TIMESTAMP WITH TIME ZONE`. Confirmed with
  `describe select * from delta_scan(...)`, not assumed. A cast would only restate what the
  writer guarantees.
- **The description is re-normalized.** Bronze's descriptions were written by
  `ingestion.schema.normalize_description()`, so on paper silver has nothing to do. But bronze
  is append-only and long-lived: rows written months apart by different parser versions sit
  side by side, and silver is where the column contract is enforced. The four rules (collapse
  runs of padding characters, collapse whitespace, trim, upper case) are idempotent, so
  re-applying them is a no-op for a correctly written row and a repair for anything else.
  **The SQL and the Python implement the same four rules and have to be kept in step** — this
  is the one piece of duplication in the component, and it is deliberate.
- **No columns that nothing asked for.** No surrogate key, no derived category, no `is_expense`
  flag. `is_internal_transfer` (T18b) is the one exception, added because T18b's own acceptance
  criteria ask for it explicitly -- see "Internal transfers" below.
- **`account_kind` is joined in from `bronze.statements` (T18a), not duplicated bronze-side.**
  What an account's balance represents (`asset`: money on hand, `liability`: debt owed) is a
  `Statement`-level fact set once per parser, not a `Transaction` one — see
  [ADR 0015](../decisions/0015-account-kind-asset-or-liability.md) for the field's own design.
  The join deduplicates `bronze.statements` down to one row per `account_id` first
  (`group by account_id`, `max(account_kind)`), because a single account can have several
  statement rows — one per period, and Scotiabank writes one per *currency* for the very same
  file — and joining on `account_id` without collapsing that first would fan every one of that
  account's transactions out into duplicate silver rows. It's a `left join`, so a transaction
  whose account has no matching statement surfaces as a loud `not_null` test failure
  (`dbt/models/silver/schema.yml`) instead of silently vanishing from an inner join.

## Continuity: the rule this component adds

`ingestion/reconciliation.py` checks one statement against itself. The dbt test checks
consecutive statements of the same account against each other, which is the only place a
*missing* statement can show up at all:

- the closing balance of a period must equal the opening balance of the next, and
- the next period must start the day after the previous one ended.

Both halves earn their place. A missing month usually shows up as a balance drift, but not if
that month's movements happen to net to zero — then only the date check catches it, and
`tests/test_dbt_silver_integration.py` covers exactly that case. Severity is dbt's default,
`error`, so a gap fails `dbt build` rather than printing a warning that is easy to scroll past.

It is a singular test, not a generic one: one query about one relation, with nothing to
parametrize. It reads the bronze source rather than a silver model because the question is
which statements were ingested at all, and silver adds nothing to a statement's balances.

**Partitioned by `currency` too, not just `user_id`/`account_id` (T18c).** A Scotiabank
statement writes two `bronze.statements` rows for one real statement — one per currency (ADR
0012), sharing `account_id` and `period_start`/`period_end` — which the test's own "two
statements covering the same period" check (intended for a genuine duplicate, e.g. a bank
regenerating a PDF) couldn't tell apart from this legitimate case, since it had no currency
signal to rule it out with. Found by actually running `dbt build` against synthetic
dual-currency Scotiabank data for the first time; fixed by adding `currency` to `Statement`
(mirroring `account_kind`'s own precedent) and to both `lag()` window functions' `partition by`.
A genuine duplicate — same account, same currency, same period — still fails: it still shares
every column in the now-wider partition key. Full reasoning in
[ADR 0016](../decisions/0016-currency-aware-statement-continuity.md), including why `currency`
is *not* additionally joined into `silver.transactions` the way `account_kind` is (it's already
there, via `Transaction.currency`, since before this task).

## Internal transfers: matching, flagging, and what stays unmatched

T18b matches a real transfer between two accounts of the same user (e.g. paying a Scotiabank
credit card from a BCP checking account) so it never counts as income or expense, using the
account_kind-aware sign rule ADR 0015 already decided: two `asset` accounts (or two `liability`
accounts) match on opposite signs; an `asset`-to-`liability` pair matches on the *same* sign,
since a checking outflow and a debt-reducing payment are both negative.

All the matching logic lives in exactly one place, `internal_transfer_matches.sql`, which every
other T18b model builds on:

- **`internal_transfer_matches`** — one row per `bronze.transactions` row, with
  `is_transfer_candidate` (within the amount/date-window neighborhood of another account's row,
  any currency) and `is_internal_transfer` (a same-currency *mutual* nearest-neighbor match — see
  ADR 0017 for why mutual nearest neighbor, not a true maximum-cardinality matching).
- **`internal_transfers`** — one row per matched pair, both legs' own details plus `day_diff`/
  `amount_diff`. A thin reshape of `internal_transfer_matches`, no matching logic of its own.
- **`unmatched_transfers`** — candidates with no mutual match, for a human to review, never
  dropped: the unpaired half of a real transfer (its counterpart hasn't been ingested, or lost a
  tie-break to a closer candidate), or a cross-currency near-miss (explicitly out of scope for
  auto-matching — no FX conversion anywhere in this project — but still surfaced, not silently
  dropped or silently matched).
- **`transactions.is_internal_transfer`** — a `left join` back to `internal_transfer_matches`
  plus `coalesce(..., false)`, so every transaction has a real boolean, never null.

`internal_transfer_matches.sql` reads `bronze.transactions`/`bronze.statements` directly, never
`ref('transactions')` — the one way `transactions.sql` can join back to it for its own flag
without creating a dependency cycle (`dbt compile` refuses to build one; confirmed against an
early draft that tried the other way). A `movement_id` macro
([`dbt/macros/movement_id.sql`](../../dbt/macros/movement_id.sql), a content hash of every
`bronze.transactions` column except `ingested_at`) is what lets `internal_transfer_matches.sql`
and `transactions.sql` agree on one row's identity without bronze having a surrogate key.

## Incremental MERGE: business key, occurrence number, and backfill (T20)

`silver.transactions` no longer rebuilds from every bronze row on every `dbt build`. It's
`materialized='incremental'`, `incremental_strategy='merge'`, keyed on the business key
[`brain/concepts/business-key.md`](../concepts/business-key.md) defines: `account_id`, `date`,
`amount`, normalized `description`, and `occurrence_number`. The incremental filter — which
bronze rows this run even looks at — is everything on a first build or `--full-refresh`, or,
once incremental, only rows whose `(source_file_sha256, ingested_at)` pair isn't already in
`{{ this }}`; `lakehouse/bronze.py` stamps one `ingested_at` per file, not per row, so a
touched file's rows are always picked up together.

**Two mechanisms, deliberately kept separate, for two different "the same movement showed up
again" cases:**

- **A `pfp backfill` (ADR 0010) that changes a row's own business key** (a parser fix
  correcting a description, say): `transactions.sql`'s own `pre_hook`,
  `purge_reprocessed_files()`, deletes that file's *existing* silver rows before the `MERGE`
  inserts the fresh ones — a plain `MERGE` alone can insert a new-keyed row and update a
  matching one, but it can never *delete* a target row whose key no longer appears in the
  run's own source data, so without the purge the row's old key would sit in silver forever,
  orphaned next to the corrected one.
- **A different file that happens to parse to the same business key** (a bank regenerating a
  statement PDF with different bytes, past T7's file-level dedup): that file was never in
  silver before, so the purge has nothing of its own to delete — the `MERGE`'s own
  `WHEN MATCHED` branch, matching on the business key rather than the file, is what correctly
  updates that row in place instead.

Full reasoning, including why these stay two mechanisms rather than one, in
[ADR 0018](../decisions/0018-incremental-merge-business-key-occurrence-number.md).

## How to use it and how to verify it

Needs SeaweedFS up and `.env` exported; `profiles.yml` lives in the project directory, so both
`--project-dir` and `--profiles-dir` are needed:

```bash
make poc-up
set -a && source .env && set +a
uv run dbt build --project-dir dbt --profiles-dir dbt
uv run sqlfluff lint dbt/models
duckdb dbt/pfp.duckdb -c "select count(*) from silver.transactions"   # optional
```

`dbt/pfp.duckdb` is a real on-disk DuckDB database, so it opens directly in any DuckDB-aware
SQL client — DBeaver included, with a built-in driver. `silver.*` shows up with zero extra
setup; seeing `bronze.*` there too needs a one-time DuckDB persistent-secret-and-views setup,
since dbt only reads bronze through `delta_scan()` at build time and never materializes it into
this file. Exact commands in [SETUP.md §7](../../SETUP.md#7-browsing-the-lake-in-dbeaver).

- [`tests/test_delta_scan_integration.py`](../../tests/test_delta_scan_integration.py) is the
  de-risking test `tasks/plan.md`'s risk log asks for: DuckDB reading bronze's Delta tables off
  local S3, kept as a test so the path stays proven as versions move. Drop `ENDPOINT`,
  `URL_STYLE` and `USE_SSL` from its secret and it fails against real AWS instead — that is
  what the risk was.
- [`tests/test_dbt_silver_integration.py`](../../tests/test_dbt_silver_integration.py) seeds
  synthetic statements into `<LAKEHOUSE_URI>/_t16_dbt_tests` (never the real `bronze/` prefix),
  runs `dbt build` against exactly that data, and checks the result — including the
  missing-month scenario failing and then passing once the gap is filled, a dual-currency
  Scotiabank statement passing (T18c: the exact false positive that used to fail), and a genuine
  same-account/same-currency/same-period duplicate still failing. A dedicated prefix is what
  makes it deterministic: the continuity test spans every statement in the lake, so it cannot be
  asserted against a lake that also holds real, partially archived periods.
- [`tests/test_dbt_incremental_merge_integration.py`](../../tests/test_dbt_incremental_merge_integration.py)
  (T20) proves, against real local S3: two identical transactions in one statement land as two
  silver rows; a second `dbt build` with no bronze changes touches nothing; a backfilled,
  corrected description updates the row in place (not both); a backfill of unchanged content
  doesn't duplicate; a regenerated file with the same business key updates in place at the
  model level; the new balance-reconciliation test passes normally and fails when a `MERGE`
  scenario is deliberately broken.
- All three are `integration`-marked and deselected by default (`pytest -m integration`), like
  T14's bronze test; see CONSTRAINTS.md's exceptions table.

## Related

- [ADR 0018: Incremental MERGE, occurrence-number business key](../decisions/0018-incremental-merge-business-key-occurrence-number.md) —
  the business key, the two backfill/regeneration mechanisms, and `movement_id`'s own
  extension, in full.
- [ADR 0016: Currency-aware statement continuity](../decisions/0016-currency-aware-statement-continuity.md) —
  the false positive found running `dbt build` against dual-currency Scotiabank data, and the
  partition-by-currency fix, in full.
- [ADR 0015: Account kind (asset/liability)](../decisions/0015-account-kind-asset-or-liability.md) —
  the `account_kinds` join described above, in full.
- [ADR 0011: `delta_scan()` as a dbt source](../decisions/0011-delta-scan-as-a-dbt-source.md) —
  every design call here, with the alternatives.
- [ADR 0002: DuckDB + delta-rs before Spark](../decisions/0002-duckdb-and-delta-rs-before-spark.md)
- [ADR 0006: Lake location by URI](../decisions/0006-lake-location-by-uri.md)
- [Lakehouse](lakehouse.md) — the bronze tables this reads.
- [Medallion architecture](../concepts/medallion.md) — why silver exists at all.
- [Reconciliation](../concepts/reconciliation.md) — the continuity level this implements.
- [Business key](../concepts/business-key.md) — the identity `transactions.sql`'s own `MERGE`
  is keyed on.
- [Idempotency](../concepts/idempotency.md)
- [Phase 1](../phases/phase-1.md)
