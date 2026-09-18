# Tasks — Phase 2: Orchestration + Governance

> Context, decisions and risks in [`plan-phase2.md`](plan-phase2.md). Each task = 1 branch from
> `develop` = 1 PR. Every task also satisfies the **Definition of Done** in `plan.md`
> (unchanged from Phase 1).

---

### T20: Business-key MERGE in silver — `feat/silver-incremental-merge`

**Description:** `silver.transactions` (T16) is a full-refresh view today — every `dbt build`
recomputes it from all of bronze. This task makes it incremental, resolving the open question
[`brain/concepts/business-key.md`](../brain/concepts/business-key.md) already flagged in T3a:
two legitimate same-day, same-amount, same-merchant purchases in one statement would
otherwise collide on one key.

**Acceptance criteria:**
- [x] `silver.transactions`'s business key is `date + amount + normalized description +
  account_id + occurrence_number`, where `occurrence_number` is a `row_number()` scoped to
  *one source file* (`source_file_sha256`) — two identical-looking rows in the same PDF get
  different numbers; the same purchase re-appearing in a regenerated PDF of the same period
  still collides (intentional — that's a duplicate, not two purchases).
- [x] The model is `materialized='incremental'`, `incremental_strategy='merge'`, keyed on that
  business key.
- [x] A `pfp backfill` (ADR 0010) re-parse of an already-ingested file correctly *updates* its
  existing silver rows via the MERGE, not skips them as already-present or duplicates them —
  via a `pre_hook` that purges a touched file's own existing rows first (ADR 0018; a plain
  `MERGE` alone can't delete a row whose key stopped appearing in a reprocessed file).
- [x] `brain/concepts/business-key.md`'s "Open question" section is updated to reflect the
  resolution, not left contradicting the code.
- [x] A new dbt test, per account per statement period: `sum(silver.transactions.amount)`
  for that period equals `bronze.statements.closing_balance - opening_balance` for the
  matching statement. This is the same arithmetic `ingestion/reconciliation.py` (T8) already
  checks once in Python at parse time — re-checked here at the model layer specifically to
  catch anything this task's own MERGE gets wrong (a silently dropped or duplicated row) that
  a check upstream of the MERGE never would.

**Verification:**
- [x] Two synthetic transactions, same date/amount/description/account, in one statement:
  both land in silver as separate rows.
- [x] The same statement's bytes re-ingested (T7's file-level dedup) never reaches this model
  a second time — unchanged from Phase 1, confirmed still true after switching to incremental.
- [x] A synthetic backfill scenario (change a fixture's description, backfill, dbt build):
  the *old* description is gone from silver, not duplicated alongside the new one.
- [x] `dbt build` a second time with no bronze changes touches nothing. (note: verified via
  full-row content-identity of `silver.transactions` before and after, not a dbt-reported
  rows-affected count — `dbt-duckdb`'s own adapter never reports one, confirmed by reading its
  `get_response()` source directly rather than assumed.)
- [x] The new balance-reconciliation test: passes on a normal synthetic fixture; fails when a
  synthetic MERGE scenario is deliberately broken (a row dropped on purpose) — proving the
  test actually catches what it's meant to, not just that it runs.

**Dependencies:** T19 (Phase 1 closed) · **Files:** `dbt/models/silver/transactions.sql`,
`dbt/models/silver/schema.yml`, `dbt/tests/`, `brain/concepts/business-key.md`, tests ·
**Size:** M · **Skill:** test-driven-development

### T21: Dagster orchestration — `feat/dagster-orchestration`

**Description:** The ingest → dbt build → test sequence becomes one Dagster DAG, wrapping the
existing `pfp` CLI and dbt project rather than reimplementing either.

**Acceptance criteria:**
- [ ] Dagster assets: a bronze asset (wraps `organizer.organize()` + `bronze.write_statement()`
  — the same functions `pfp ingest` already calls, not a shelled-out subprocess), a silver
  asset (`dbt build --select silver`, via `dagster-dbt`'s dbt Cloud/core integration), and
  their dependency edges match the real data flow.
- [ ] `uv run dagster asset materialize --select '*'` runs the whole pipeline locally, end to
  end, against a real (or ephemeral) lake — same result as running `pfp ingest` then
  `dbt build` by hand.
- [ ] CI's `ephemeral-integration` job (T17) is updated to invoke the Dagster job itself where
  it currently calls `pfp ingest`/`dbt build` directly, so CI proves the path a real install
  actually uses, not a bypass of it.
- [ ] `make poc` and the raw CLI commands still work unchanged for local single-shot use —
  Dagster owns the DAG'd/scheduled path, it doesn't replace the manual one (Piero's own
  masked-dump debugging loop, ADR 0004, still needs `pfp parse` directly, no DAG in the way).

**Verification:**
- [ ] A fresh synthetic inbox, materialized through Dagster, produces the identical bronze +
  silver row counts as the equivalent `pfp ingest` + `dbt build` sequence.
- [ ] Dagster's own asset lineage UI (or `dagster asset list`) shows the bronze -> silver
  dependency correctly.
- [ ] CI's `ephemeral-integration` job green with the Dagster-invoked path.

**Dependencies:** T20 · **Files:** `dagster/**`, `.github/workflows/ci.yml`, `Makefile`,
`pyproject.toml` · **Size:** L · **Skill:** ci-cd-and-automation

### T22: Elementary — `feat/elementary-quality`

**Description:** dbt-native data quality and observability — anomaly detection and
column-level lineage, no new infrastructure (chosen over Great Expectations for exactly this,
`tasks/plan-phase2.md`).

**Acceptance criteria:**
- [ ] Elementary installed as a dbt package (`packages.yml`), its own models built alongside
  silver/gold in the same `dbt build`.
- [ ] At least one real anomaly test on `silver.transactions` (e.g. row-count or freshness
  anomaly detection) — not just the package installed with nothing configured.
- [ ] `elementary monitor report` (or `edr report`) produces a real local report from this
  project's own data (synthetic, per ADR 0004).
- [ ] CI runs Elementary's tests as part of the existing `ephemeral-integration` job (T17),
  warn-mode initially (mirrors how Phase 1's own numeric rules started in warn mode,
  CONSTRAINTS.md).

**Verification:**
- [ ] A deliberately broken synthetic scenario (e.g. a sudden row-count spike) is flagged by
  Elementary's anomaly detection; a normal run isn't.
- [ ] The report renders and is human-readable, checked by actually opening it, not just
  confirming the command exits 0.

**Dependencies:** T20 · **Files:** `dbt/packages.yml`, `dbt/models/**`,
`.github/workflows/ci.yml`, `SETUP.md` · **Size:** M · **Skill:** test-driven-development

### T23: Gold star schema — `feat/gold-star-schema`

**Description:** `fact_transactions` + dimensions — the shape a BI tool or a future ML
feature pipeline actually wants, not silver's flat table.

**Acceptance criteria:**
- [x] `dim_date`, `dim_account` (carries `account_kind`, T18a, and `bank`), `dim_user`,
  `dim_bank`: each with a clear grain, stated in its own `schema.yml` description.
- [x] `fact_transactions`: one row per business key (T20), foreign keys into every dimension
  above, `amount`/`currency`/`date` as measures/degenerate attributes. `currency` is never
  collapsed or converted — every currency-sliced query stays sliced (no FX, Piero's explicit
  call, `tasks/plan-phase2.md`'s architecture decisions).
- [x] `fact_transactions` gains `flow_type`: `ingreso` / `egreso` / `pago`, derived from
  `account_kind` (T18a) + `amount`'s sign, not each bank's own raw sign convention directly —
  `asset`+positive -> `ingreso`, `asset`+negative -> `egreso`, `liability`+positive (a charge)
  -> `egreso`, `liability`+negative (a payment/credit) -> `pago` (its own bucket, not folded
  into `ingreso` — usually a transfer from the user's own other account, already flagged by
  `is_internal_transfer` from T18b, or a refund; genuinely ambiguous which, so it isn't
  counted as income either way). Every spend/income aggregate in this task's own verification
  filters `is_internal_transfer = false`, so a credit-card payment funded by a same-user
  transfer is never double-counted as an expense on one side and silently untouched on the
  other. `flow_type` is direction only — it doesn't anticipate or touch Phase 3's
  `dim_category`.
- [x] No `dim_category` yet — Phase 3's, not built ahead of the model that fills it (see
  `tasks/plan-phase2.md`'s architecture decisions for why).
- [x] `dim_account`'s grain confirmed (one row per `account_id` ever seen, no SCD — see
  `tasks/plan-phase2.md`'s open questions) or built as an SCD if that turns out wrong.
  (Confirmed, not built as an SCD: `account_kind`/`bank` are fixed per parser, ADR 0015, and
  never change for a given `account_id` after the fact — full reasoning in ADR 0020.)

**Verification:**
- [x] Row count of `fact_transactions` equals `silver.transactions`' row count exactly (a
  1:1 fact, no fan-out from a dimension join). (Verified for real:
  `test_fact_transactions_row_count_matches_silver_transactions_exactly` in
  `tests/test_dbt_gold_integration.py`, plus the standing dbt test
  `assert_fact_transactions_row_count_matches_silver.sql` that runs on every `dbt build`.)
- [x] Every foreign key in `fact_transactions` resolves to exactly one dimension row
  (dbt `relationships` tests on every FK, not just `not_null`). (Verified for real against a
  live SeaweedFS: `dbt build` green with all four `relationships_fact_transactions_*` tests
  present and passing, grepped by name in
  `test_every_foreign_key_in_fact_transactions_resolves_via_relationships_tests`.)
- [x] A synthetic query joining `fact_transactions` to all four dimensions produces a
  believable answer (e.g. "spend by bank by month") — run for real, not just modeled.
  (`test_spend_by_bank_by_month_query_joins_all_four_dimensions`: BCP 50.00, Scotiabank 165.00
  for January 2026, matching the fixture by hand.)
- [x] A synthetic scenario with one BCP checking account and one Scotiabank credit card, and a
  transfer between them (T18b): summed `egreso` across both accounts, filtered to
  `is_internal_transfer = false`, matches the expected total by hand — proving `flow_type`
  gives a coherent cross-bank answer despite BCP and Scotiabank's opposite raw sign
  conventions, and that the transfer itself doesn't inflate it.
  (`test_cross_bank_egreso_sum_excludes_the_internal_transfer`: filtered total 215.00 PEN,
  matching 50.00 BCP grocery + 120.00 + 45.00 Scotiabank charges by hand; the *unfiltered*
  total is 515.00, showing the BCP transfer leg would otherwise inflate it by exactly its own
  300.00 — run for real against a live, isolated SeaweedFS instance, `pfp-t23-gold`.)

**Dependencies:** T20 · **Files:** `dbt/models/gold/**`, tests · **Size:** M · **Skill:**
test-driven-development

### T24: OpenMetadata catalog and lineage — `infra/openmetadata`

**Description:** Column-level lineage and a browsable catalog, ingesting from dbt's own
manifest and DuckDB's catalog. Chosen over DataHub for a lighter footprint
(`tasks/plan-phase2.md`) — but "lighter than DataHub" still means real resource cost, checked
first, not assumed.

**Acceptance criteria:**
- [ ] **First, before anything else in this task:** OpenMetadata's `docker compose` stack
  (Postgres/MySQL + Elasticsearch/OpenSearch + the OpenMetadata server) actually starts and
  stays healthy on this machine's real WSL2 `.wslconfig` limit, with everything else Phase 1
  already runs (SeaweedFS) also up — measured RAM/CPU noted in the PR, not assumed from the
  vendor's own minimums. If it doesn't fit, stop and bring the shortfall back to Piero before
  building anything on top of it (the fallback — a lighter catalog, or deferring this task past
  phase close — gets decided then, per `tasks/plan-phase2.md`'s risk log).
- [ ] An ingestion workflow pulls dbt's `manifest.json` + `catalog.json` (dbt's own metadata
  artifacts, already produced by every `dbt build`) into OpenMetadata: every silver/gold
  model, its columns, and its lineage back through to `bronze.transactions`.
- [ ] Column-level lineage is real, not table-level only: `fact_transactions.amount` traces
  back to `bronze.transactions.amount`, through every model in between.
- [ ] `docker-compose.yml` (or a dedicated `openmetadata/docker-compose.yml`) follows the same
  ephemeral, project-named, `down -v` pattern as the rest of this repo (ADR 0007) — this is
  optional infrastructure for local exploration, not something CI is expected to run per PR
  given the RAM cost above; note this explicitly rather than silently wiring it into CI.

**Verification:**
- [ ] Real RAM/CPU measurement pasted into the PR (`docker stats` or equivalent) alongside
  the `.wslconfig` limit it was measured against.
- [ ] A screenshot or `curl`'d API response showing `fact_transactions`' real column-level
  lineage in the running OpenMetadata instance.

**Dependencies:** T21, T23 · **Files:** `openmetadata/**`, `SETUP.md`, `brain/**` · **Size:** L
· **Skill:** ci-cd-and-automation

### T25: Phase 2 close — `docs/phase-2-close`

**Description:** Leave the phase presentable, mirroring T19's own close of Phase 1.

**Acceptance criteria:**
- [ ] `README.md`: Phase 2's status row added to the existing progress table (not a rewrite —
  same pattern T19 used for Phase 1).
- [ ] Brain kept current: `brain/phases/phase-2.md` (new, mirrors `phase-1.md`'s shape),
  every new component/concept/decision note cross-linked.
- [ ] `PROJECT.md` checked against what was actually built vs. planned; any deviation noted.

**Verification:**
- [ ] Clone the repo into a clean folder and follow the README through to a materialized
  Dagster DAG with no missing steps.

**Dependencies:** T20, T21, T22, T23, T24 · **Files:** `README.md`, `brain/**`, `PROJECT.md` ·
**Size:** S

### ✅ Final checkpoint (Phase 2)
- [ ] All criteria met · [ ] `develop → main` release PR "Phase 2 — Orchestration + Governance"
  · [ ] merged by Piero
