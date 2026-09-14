---
type: component
phase: 1
status: built
task: T16
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
| [`dbt/models/silver/transactions.sql`](../../dbt/models/silver/transactions.sql) | `silver.transactions`: bronze's columns with the description re-normalized, plus `account_kind` joined in from `bronze.statements` (T18a). Materialized as a table |
| [`dbt/models/silver/schema.yml`](../../dbt/models/silver/schema.yml) | `not_null` on every column, `accepted_values` on `currency` (`PEN`, `USD`) and `account_kind` (`asset`, `liability`), matching `ingestion.schema.Currency`/`AccountKind` |
| [`dbt/tests/assert_statement_continuity.sql`](../../dbt/tests/assert_statement_continuity.sql) | The continuity test: a period's closing balance is the next period's opening balance, and the periods are contiguous, per user and account |
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
  flag. `is_internal_transfer` arrives in T18b, with the model that can populate it.
- **`account_kind` is joined in from `bronze.statements` (T18a), not duplicated bronze-side.**
  What an account's balance represents (`asset`: money on hand, `liability`: debt owed) is a
  `Statement`-level fact set once per parser, not a `Transaction` one — see
  [ADR 0014](../decisions/0014-account-kind-asset-or-liability.md) for the field's own design.
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
  missing-month scenario failing and then passing once the gap is filled. A dedicated prefix is
  what makes it deterministic: the continuity test spans every statement in the lake, so it
  cannot be asserted against a lake that also holds real, partially archived periods.
- Both are `integration`-marked and deselected by default (`pytest -m integration`), like T14's
  bronze test; see CONSTRAINTS.md's exceptions table.

## Related

- [ADR 0014: Account kind (asset/liability)](../decisions/0014-account-kind-asset-or-liability.md) —
  the `account_kinds` join described above, in full.
- [ADR 0011: `delta_scan()` as a dbt source](../decisions/0011-delta-scan-as-a-dbt-source.md) —
  every design call here, with the alternatives.
- [ADR 0002: DuckDB + delta-rs before Spark](../decisions/0002-duckdb-and-delta-rs-before-spark.md)
- [ADR 0006: Lake location by URI](../decisions/0006-lake-location-by-uri.md)
- [Lakehouse](lakehouse.md) — the bronze tables this reads.
- [Medallion architecture](../concepts/medallion.md) — why silver exists at all.
- [Reconciliation](../concepts/reconciliation.md) — the continuity level this implements.
- [Phase 1](../phases/phase-1.md)
