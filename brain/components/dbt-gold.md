---
type: component
phase: 2
status: built
task: T23
---

# dbt gold

A dbt-duckdb project that reads `silver.transactions` and builds `gold`'s star schema —
`fact_transactions` plus `dim_date`, `dim_account`, `dim_bank`, `dim_user` — the shape a BI
tool or a future ML feature pipeline actually wants, not silver's flat table. Design decisions
in [ADR 0020](../decisions/0020-gold-star-schema-flow-type-and-dim-account-grain.md).

## Pieces

| Piece | What it does |
|---|---|
| [`dbt/macros/generate_schema_name.sql`](../../dbt/macros/generate_schema_name.sql) | T23: overrides dbt-core's own default so a model's `+schema:` config becomes that schema verbatim (`gold.fact_transactions`, not dbt's own default `silver_gold.fact_transactions`). Silver's models set no `+schema:`, so they're unaffected |
| `gold: +schema: gold` in [`dbt/dbt_project.yml`](../../dbt/dbt_project.yml) | T23: opts every model under `dbt/models/gold/` into the `gold` schema, via the macro above |
| [`dbt/models/gold/dim_date.sql`](../../dbt/models/gold/dim_date.sql) | `gold.dim_date`: one row per calendar date that appears in `silver.transactions` (grain), with the standard date-part breakdowns (year/quarter/month/day, names, weekend flag). Not a generated calendar spine — see the model's own docstring |
| [`dbt/models/gold/dim_account.sql`](../../dbt/models/gold/dim_account.sql) | `gold.dim_account`: one row per `account_id` (grain), carrying `bank`, `account_last4`, `account_kind`. No slowly-changing-dimension handling — confirmed, not assumed, in ADR 0020 |
| [`dbt/models/gold/dim_bank.sql`](../../dbt/models/gold/dim_bank.sql) | `gold.dim_bank`: one row per distinct `bank` name (grain). Kept separate from `dim_account` so a bank-level query can join straight to it |
| [`dbt/models/gold/dim_user.sql`](../../dbt/models/gold/dim_user.sql) | `gold.dim_user`: one row per distinct `user_id` (grain). No attribute beyond the id itself — this project never collects a name or email |
| [`dbt/models/gold/fact_transactions.sql`](../../dbt/models/gold/fact_transactions.sql) | `gold.fact_transactions`: one row per `silver.transactions` business key (grain, T20) — a straight `select`, no join, so nothing can fan a row out. Foreign keys into every dimension above are the natural keys themselves (`account_id`, `bank`, `user_id`, `date`), never a surrogate key. Carries `amount`/`currency`/`date` as measures/degenerate attributes (`currency` never collapsed or converted — no FX, ever) and derives `flow_type` |
| [`dbt/models/gold/schema.yml`](../../dbt/models/gold/schema.yml) | Each dimension's own grain, stated in its `description`; `not_null` + `unique` on every dimension's key; `relationships` tests on every FK in `fact_transactions` (`account_id`, `bank`, `user_id`, `date`), not just `not_null`; `accepted_values` on `currency` and `flow_type` |
| [`dbt/tests/assert_fact_transactions_row_count_matches_silver.sql`](../../dbt/tests/assert_fact_transactions_row_count_matches_silver.sql) | T23: standing proof `fact_transactions` is a genuine 1:1 fact — `count(*)` matches `silver.transactions` exactly, every `dbt build` |

## `flow_type`: direction, not each bank's own raw sign

`ingreso` / `egreso` / `pago`, derived from `account_kind` (T18a, ADR 0015) + `amount`'s sign —
never each bank's own raw sign convention directly, since BCP (asset) and Scotiabank
(liability) read the *same* real-world direction with *opposite* signs:

| `account_kind` | `amount` sign | `flow_type` |
|---|---|---|
| `asset` | positive | `ingreso` |
| `asset` | negative | `egreso` |
| `liability` | positive (a charge) | `egreso` |
| `liability` | negative (a payment/credit) | `pago` |

`pago` is its own bucket, not folded into `ingreso`: a negative-signed liability movement is
usually a same-user transfer (already flagged separately by `is_internal_transfer`, T18b) or a
refund — genuinely ambiguous which, so it's never counted as income either way. Every
spend/income aggregate over `fact_transactions` must filter `is_internal_transfer = false`, or
a credit-card payment funded by a same-user transfer gets double-counted as an expense on one
side and silently untouched on the other. `flow_type` is direction only — it doesn't anticipate
or touch Phase 3's future `dim_category`; no `dim_category` exists in this project yet, on
purpose (`tasks/plan-phase2.md`'s own architecture decisions).

Full reasoning, including why the mapping has no catch-all `else` branch, in
[ADR 0020](../decisions/0020-gold-star-schema-flow-type-and-dim-account-grain.md).

## No FX, ever

`currency` is carried through from `silver.transactions` unchanged and never collapsed or
converted — every currency-sliced query (gold included) stays sliced. Piero's explicit call
(`tasks/plan-phase2.md`): an FX rate is one more moving, external input this project would have
to source and keep current, for a number nobody asked for.

## How to use it and how to verify it

Needs SeaweedFS up and `.env` exported, same as silver:

```bash
make poc-up
set -a && source .env && set +a
uv run dbt build --project-dir dbt --profiles-dir dbt
uv run sqlfluff lint dbt/models
duckdb dbt/pfp.duckdb -c "select count(*) from gold.fact_transactions"   # optional
```

- [`tests/test_dbt_gold_integration.py`](../../tests/test_dbt_gold_integration.py) (T23) proves,
  against real local S3: `fact_transactions`' row count matches `silver.transactions` exactly;
  every FK's own `relationships` test actually runs (grepped by name, not just "the build was
  green"); the full `flow_type` mapping for all four `account_kind`/sign combinations; the
  cross-bank BCP checking + Scotiabank credit-card transfer scenario (summed `egreso`, filtered
  to `is_internal_transfer = false`, matches the expected total by hand, and the *unfiltered*
  total is shown to be wrong — inflated by the transfer's own leg — to prove the filter is
  load-bearing); and a "spend by bank by month" query joined across all four dimensions.
- `integration`-marked and deselected by default (`pytest -m integration`), like the rest of the
  dbt integration suite; see `CONSTRAINTS.md`'s exceptions table for its own approved row.

## Not built here, on purpose

- **`dim_category`.** Phase 3's own future task — building it now would be schema speculation
  ahead of the categorization model that fills it (`tasks/plan-phase2.md`'s architecture
  decisions).
- **`brain/phases/phase-2.md`.** Doesn't exist yet as of this PR. `tasks/plan-phase2.md`'s own
  task table lists T25 ("Phase 2 close") as the task that closes the phase, the same role
  `brain/phases/phase-1.md` played for Phase 1 — this PR leaves it for whichever task closes
  Phase 2 (T25, or a sibling task if T25 hasn't landed yet), rather than creating a partial one
  that three more Phase 2 tasks (T21, T22, T24) would each also need to extend in parallel.

## Related

- [ADR 0020: Gold star schema, `flow_type`, `dim_account`'s no-SCD confirmation](../decisions/0020-gold-star-schema-flow-type-and-dim-account-grain.md) —
  every design call here, with the alternatives.
- [ADR 0015: Account kind (asset/liability)](../decisions/0015-account-kind-asset-or-liability.md) —
  the sign convention `flow_type` is built on.
- [ADR 0017: Internal-transfer matching](../decisions/0017-internal-transfer-matching-mutual-nearest-neighbor.md) —
  `is_internal_transfer`, carried through onto `fact_transactions` unchanged.
- [ADR 0018: Incremental MERGE, occurrence-number business key](../decisions/0018-incremental-merge-business-key-occurrence-number.md) —
  the business key `fact_transactions`' own grain is identical to.
- [dbt silver](dbt-silver.md) — the source this whole layer reads from.
- [Medallion architecture](../concepts/medallion.md) — why gold exists at all.
- [Business key](../concepts/business-key.md)
- [Phase 1](../phases/phase-1.md)
