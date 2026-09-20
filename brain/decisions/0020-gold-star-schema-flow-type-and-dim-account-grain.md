---
type: decision
phase: 2
status: accepted
date: 2026-09-17
---

# ADR 0020: Gold star schema — grain, `flow_type`, and `dim_account`'s no-SCD confirmation

## Context

Phase 2's gold layer (T23) needs to give a BI tool or a future ML feature pipeline the shape it
actually wants — `fact_transactions` + dimensions — instead of `silver.transactions`' flat
table. `tasks/plan-phase2.md`'s own architecture decisions already fixed the load-bearing
calls before this task started: the star shape itself (`fact_transactions`, `dim_date`,
`dim_account`, `dim_user`, `dim_bank`, explicitly no `dim_category` yet), no FX conversion
anywhere, and the exact `flow_type` mapping (`account_kind` + `amount`'s sign, not each bank's
own raw sign convention). What was left for this task: how the dimensions are actually built
(grain, keys, materialization) and the one open question the plan flagged rather than assumed —
whether `dim_account` needs slowly-changing-dimension handling.

## Decision

**Natural keys, not surrogate ones.** Every dimension's own natural key (`account_id`, `bank`,
`user_id`, `date`) is also `fact_transactions`' own foreign key column — no
`generate_surrogate_key()`-style hash, no integer sequence. This project has no separate
master-data source for accounts, banks or users to generate a surrogate key *against*; every
dimension here is itself derived from `silver.transactions`, the same table
`fact_transactions` reads. A natural key resolves every FK by construction and is simpler to
read and test (`relationships` tests compare the same values a human would), so a surrogate key
would only add an extra hash with nothing real to protect against.

**Every dimension is `select distinct <key columns> from {{ ref('transactions') }}`** (or the
`group by` + `max()` equivalent for `dim_account`, see below) — never a separate read from
`bronze.statements` or anywhere else. This guarantees referential integrity *by construction*:
every value `fact_transactions` can ever carry in a natural-key column already has a
corresponding dimension row, because both are built from the same source. The
`relationships` tests in `dbt/models/gold/schema.yml` are the standing proof of this, not a
hopeful assumption.

**`fact_transactions` is a straight `select` from `{{ ref('transactions') }}`, no join.**
Every dimension lookup is a natural key already present on the silver row — nothing needs
joining in to resolve an FK. This is what makes the "one row per business key, no fan-out"
acceptance criterion trivially true rather than something to verify after the fact: there is no
join in this model that *could* fan a row out.

**`dim_account`'s grain: one row per `account_id`, no slowly-changing-dimension handling —
confirmed, not assumed.** `tasks/plan-phase2.md`'s own open question asked this to be checked
rather than taken on faith. The check: `account_kind` and `bank` are set once, per parser,
hardcoded (ADR 0015) — `ingestion/parsers/bcp.py` always writes `account_kind="asset"`,
`ingestion/parsers/scotiabank.py` always writes `account_kind="liability"`, and `bank` follows
the same per-parser constant. Neither value is read from a specific statement's own content, so
there is no real-world event ("the bank changed my account's product type") this project could
ever observe that would make a given `account_id`'s `account_kind` or `bank` legitimately
different between two of its own statements. An SCD exists to answer "what did this dimension
attribute look like *as of* a given fact row" when the attribute genuinely varies over time;
here it structurally cannot, so an SCD would add versioning machinery with nothing for it to
version. `dim_account.sql` still defends against a *data* disagreement the same way
`silver.transactions`' own `account_kinds` CTE already does (ADR 0015): `group by account_id`
+ `max(bank)`/`max(account_last4)`/`max(account_kind)`, not `select distinct`, so a real
(currently impossible, not currently enforced) disagreement collapses to one deterministic
value and one dimension row, rather than fanning `dim_account` — and so
`fact_transactions`' own `relationships` test — out into two rows for one account.

**`dim_bank` stays a separate dimension from `dim_account`**, even though `dim_account` already
carries `bank`. `fact_transactions.bank` is a direct FK into it, so a bank-level query ("spend
by bank by month") can join straight to `dim_bank`, without going through account-level detail
it doesn't need. A small, deliberate amount of the "outrigger" shape a strict single-fan star
schema would avoid — justified here because the acceptance criteria's own verification query is
exactly a bank-level, not account-level, aggregate.

**(Superseded in T34, see below) `dim_date` is derived from the dates that actually occur in
`silver.transactions`, not a generated calendar spine.** A spine needs an arbitrary start/end range to generate for a
project with no fixed reporting horizon; this project's own "no columns or rows nothing asked
for" discipline (already stated for silver in `brain/components/dbt-silver.md`) applies the
same way here. The standard date-part columns (year/quarter/month/day, names, weekend flag)
are cheap, common attributes a "spend by month" query wants without re-deriving them per query
— not speculative beyond that (no fiscal calendar, no holiday calendar).

**`flow_type`** (`dbt/models/gold/fact_transactions.sql`): a `case` expression on
`account_kind` + `amount`'s sign, verbatim from `tasks/plan-phase2.md`'s own architecture
decisions and `tasks/todo-phase2.md`'s T23 entry:

| `account_kind` | `amount` sign | `flow_type` |
|---|---|---|
| `asset` | positive | `ingreso` |
| `asset` | negative | `egreso` |
| `liability` | positive (a charge) | `egreso` |
| `liability` | negative (a payment/credit) | `pago` |

No catch-all `else`: `amount` is guaranteed non-zero
(`ingestion.schema.Transaction._validate_amount`) and `account_kind` is guaranteed to be
exactly `asset` or `liability` (`dbt/models/silver/schema.yml`'s own `accepted_values` test),
so these four branches are exhaustive for every row that can legitimately reach this model — a
row that somehow violated that surfaces as a loud `null` (this model's own `not_null` test on
`flow_type`), never a silently wrong bucket. `pago` stays its own bucket rather than folding
into `ingreso`, because a negative-signed liability movement is usually a same-user transfer
(already flagged separately by `is_internal_transfer`, T18b) or a refund — genuinely ambiguous
which, so it is never counted as income either way.

**Schema-per-layer, via a `generate_schema_name` override.** `dbt/macros/generate_schema_name.sql`
replaces dbt-core's own default (`<target_schema>_<custom_schema>`) with the custom schema
name verbatim, so `dbt/dbt_project.yml`'s `gold: +schema: gold` produces `gold.fact_transactions`,
not the uglier `silver_gold.fact_transactions` dbt would otherwise generate. Silver's own
models set no `+schema:`, so `custom_schema_name` is `none` for them and they keep landing in
`target.schema` ("silver", `dbt/profiles.yml`) exactly as before — this override only changes
behavior for a model that opts in, which today is only `dbt/models/gold/**`.

## Alternatives considered

- **Surrogate integer or hash keys for every dimension.** Rejected: no source of truth for
  accounts/banks/users/dates exists independently of `silver.transactions` itself, so a
  surrogate key would be an extra layer of indirection over data that's already uniquely and
  stably identified by its own natural key, for no correctness or performance gain at this
  project's scale (thousands of rows).
- **An SCD Type 2 `dim_account`** (`valid_from`/`valid_to`, a row per version). Rejected per the
  Decision section above: nothing in this project can make `account_kind` or `bank` vary for a
  given `account_id` after the fact, so there is no real change event for an SCD to capture —
  building one now would be exactly the kind of speculative complexity this project's own
  "simplest thing that meets the criteria" rule (`CLAUDE.md`) rejects elsewhere.
- **A generated calendar spine for `dim_date`** (e.g. every date in a fixed year range).
  Rejected: this project has no fixed reporting horizon to pick a range against, and a spine
  would add dates `fact_transactions` can never reference — rows nothing asked for, the same
  reasoning silver already applies to its own columns.
- **Dropping `dim_bank` as redundant with `dim_account.bank`.** Considered, since every
  `fact_transactions.bank` value is already reachable by joining through `dim_account`.
  Rejected: `tasks/todo-phase2.md`'s own acceptance criteria list `dim_bank` as a required,
  separate dimension, and the required "spend by bank by month" verification query is a
  bank-level, not account-level, aggregate — a direct FK avoids an unnecessary extra join for
  exactly the query this task has to prove works.

## Consequences

- `dbt/macros/generate_schema_name.sql` is now a project-wide macro: any *future* model that
  sets its own `+schema:` inherits the same "use it verbatim" behavior, not just gold's models.
  Documented here so a later task doesn't rediscover it by surprise.
- `fact_transactions` inherits every one of `silver.transactions`' own known, pre-existing
  limitations unchanged (ADR 0018's own business-key caveats, e.g. no `user_id`/`currency` in
  the key) — this task adds no new ones.
- No `dim_category` exists yet, on purpose (`tasks/plan-phase2.md`'s own architecture
  decisions) — Phase 3's own future task builds it; `flow_type` is direction only and doesn't
  anticipate it.

## Related

- [dbt gold](../components/dbt-gold.md) — the component this ADR documents.
- [ADR 0015: `account_kind` (asset/liability)](0015-account-kind-asset-or-liability.md) — the
  sign convention `flow_type` is built on, and the `account_kinds` `group by`/`max()` pattern
  `dim_account.sql` follows.
- [ADR 0017: Internal-transfer matching](0017-internal-transfer-matching-mutual-nearest-neighbor.md) —
  `is_internal_transfer`, carried through unchanged onto `fact_transactions`, and why every
  spend/income aggregate over it must filter on that column.
- [ADR 0018: Incremental MERGE, occurrence-number business key](0018-incremental-merge-business-key-occurrence-number.md) —
  the business key `fact_transactions`' own grain is identical to.
- [Business key](../concepts/business-key.md)
- [dbt silver](../components/dbt-silver.md) — the source this whole layer reads from.
- [Phase 1](../phases/phase-1.md) — `brain/phases/phase-2.md` doesn't exist yet at the time of
  this PR; see `brain/components/dbt-gold.md`'s own note on why this PR doesn't create it.

## Update 2026-09-20 (T34): `dim_date` is now a continuous calendar

The "no spine" call above assumed one fact. With three facts (movements, statement balances,
investment months) sharing one BI dashboard, the calendar has to cover all of them, and a month
without a movement still has to exist. `dim_date` is now one row per day from the first day of the
first month to the last day of the last month **any** fact has data for: the range comes from the
data, so the original objection (an arbitrary hard-coded start and end) still does not apply. The
balances and investments join it on `month_start`; a `relationships` test guards that every fact
date resolves. `gold.rpt_movements`, `rpt_balances` and `rpt_investments` join each fact to it and
expose the same `calendar_year`, `calendar_quarter` and `calendar_month` columns, so one BI filter
applies to every chart (a Superset dataset has no relationships of its own).
