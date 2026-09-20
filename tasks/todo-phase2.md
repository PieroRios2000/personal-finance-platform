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
- [x] Dagster assets: a bronze asset (wraps `organizer.organize()` + `bronze.write_statement()`
  — the same functions `pfp ingest` already calls, not a shelled-out subprocess), a silver
  asset (`dbt build --select silver`, via `dagster-dbt`'s dbt Cloud/core integration), and
  their dependency edges match the real data flow. (Deviation, noted in the PR: the whole dbt
  project is one `dagster-dbt` multi-asset — one Dagster asset key per dbt node — rather than a
  single hardcoded `--select silver` asset, so a future model (T23's gold layer already landed
  this way) becomes a Dagster asset automatically, with no per-model wiring to keep in sync.
  The dependency-edge requirement is met the same way either way, verified for real below.)
- [x] `uv run dagster asset materialize --select '*'` runs the whole pipeline locally, end to
  end, against a real (or ephemeral) lake — same result as running `pfp ingest` then
  `dbt build` by hand. (Needs `DAGSTER_MODULE_NAME=orchestration.definitions`, `.env.example` —
  not the same mechanism as `pyproject.toml`'s `[tool.dagster]` block, see ADR 0021.)
- [x] CI's `ephemeral-integration` job (T17) is updated to invoke the Dagster job itself where
  it currently calls `pfp ingest`/`dbt build` directly, so CI proves the path a real install
  actually uses, not a bypass of it. (ADR 0021.)
- [x] `make poc` and the raw CLI commands still work unchanged for local single-shot use —
  Dagster owns the DAG'd/scheduled path, it doesn't replace the manual one (Piero's own
  masked-dump debugging loop, ADR 0004, still needs `pfp parse` directly, no DAG in the way).
  (Confirmed by diff, not re-run: neither `Makefile` nor `scripts/poc.py` is touched anywhere
  in this branch — `make poc` runs against Piero's own real inbox and his own running
  `pfp-poc-seaweedfs-1` instance, which this task does not touch, per this repo's own standing
  rule never to run that command or stop that container on Piero's behalf.)

**Verification:**
- [x] A fresh synthetic inbox, materialized through Dagster, produces the identical bronze +
  silver row counts as the equivalent `pfp ingest` + `dbt build` sequence.
  (`tests/test_dagster_pipeline_integration.py`, run for real against a live, isolated
  SeaweedFS instance: 4 transactions, `DEFAULT_MOVEMENTS`, matching a manual `pfp ingest` +
  `dbt build` baseline run first for comparison.)
- [x] Dagster's own asset lineage UI (or `dagster asset list`) shows the bronze -> silver
  dependency correctly. (`uv run dagster asset list -m orchestration.definitions` and
  `tests/test_dagster_definitions.py::test_silver_transactions_depends_on_the_bronze_asset`.)
- [x] CI's `ephemeral-integration` job green with the Dagster-invoked path. (Simulated the
  exact CI steps by hand against a live, isolated SeaweedFS instance — both materialize passes,
  the idempotency check, `sqlfluff lint`, all green; real GitHub Actions run still pending,
  same as every other task in this project, per `brain/components/ci.md`'s own standing note.)

**Dependencies:** T20 · **Files:** `dagster/**`, `.github/workflows/ci.yml`, `Makefile`,
`pyproject.toml` · **Size:** L · **Skill:** ci-cd-and-automation

### T22: Elementary — `feat/elementary-quality`

**Description:** dbt-native data quality and observability — anomaly detection and
column-level lineage, no new infrastructure (chosen over Great Expectations for exactly this,
`tasks/plan-phase2.md`).

**Acceptance criteria:**
- [x] Elementary installed as a dbt package (`packages.yml`), its own models built alongside
  silver/gold in the same `dbt build`. (`dbt/packages.yml` pins `elementary-data/elementary`
  0.26.0; `dbt/dbt_project.yml`'s `elementary: +schema: "elementary"` and `on-run-end` hook.
  Confirmed against a live, isolated SeaweedFS instance: `dbt build` populates
  `elementary.dbt_run_results`/`elementary_test_results`/etc. in the same run as
  `silver.transactions` and `gold.fact_transactions`.)
- [x] At least one real anomaly test on `silver.transactions` (e.g. row-count or freshness
  anomaly detection) — not just the package installed with nothing configured.
  (`elementary.volume_anomalies` on `transactions.date`, `dbt/models/silver/schema.yml`,
  `severity: warn`, ADR 0022.)
- [x] `elementary monitor report` (or `edr report`) produces a real local report from this
  project's own data (synthetic, per ADR 0004). (`uv run edr report ...` against the live
  instance produced a real, self-contained 5.7 MB HTML report; its embedded payload contains
  the anomaly test's own `volume_anomalies`/`warn` data. `dbt/.edr/config.yml` disables
  Elementary's own anonymous tracking so the report doesn't phone home.)
- [x] CI runs Elementary's tests as part of the existing `ephemeral-integration` job (T17),
  warn-mode initially (mirrors how Phase 1's own numeric rules started in warn mode,
  CONSTRAINTS.md). (`severity: warn` at the dbt-test level, plus a dedicated
  `continue-on-error: true` "elementary anomaly tests" step and an `edr report` step, both in
  `.github/workflows/ci.yml`'s `ephemeral-integration` job. `dbt deps` added in the three
  places that needed it — see ADR 0022.)

**Verification:**
- [x] A deliberately broken synthetic scenario (e.g. a sudden row-count spike) is flagged by
  Elementary's anomaly detection; a normal run isn't.
  (`tests/test_elementary_anomaly_integration.py`, run for real against a live, isolated
  SeaweedFS instance: a normal day's count stays `PASS`; an 8x spike fires `WARN`, checked both
  in `dbt build`'s own console output and by querying `elementary.elementary_test_results`
  directly.)
- [x] The report renders and is human-readable, checked by actually opening it, not just
  confirming the command exits 0. (Opened the generated `elementary_report.html`: a real,
  self-contained React app with the "Elementary Data" title and the anomaly test's own data —
  `volume_anomalies`, `warn`, `row_count` — present in its embedded payload, not just a blank
  shell.)

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
- [x] **First, before anything else in this task:** OpenMetadata's `docker compose` stack
  (Postgres/MySQL + Elasticsearch/OpenSearch + the OpenMetadata server) actually starts and
  stays healthy on this machine's real WSL2 `.wslconfig` limit, with everything else Phase 1
  already runs (SeaweedFS) also up — measured RAM/CPU noted in the PR, not assumed from the
  vendor's own minimums. If it doesn't fit, stop and bring the shortfall back to Piero before
  building anything on top of it (the fallback — a lighter catalog, or deferring this task past
  phase close — gets decided then, per `tasks/plan-phase2.md`'s risk log).
  (Fits. WSL2 `memory=11GB processors=6 swap=4GB` -> Docker sees 14.88 GiB / 6 CPUs (official
  minimum: 6 GiB / 4 vCPUs). Idle with Piero's SeaweedFS up: ~4.6 GiB of containers. Peak while
  this task's own ingestion ran: 4.76 GiB and 457 % CPU for the stack, 1.85 GiB / 446 % for the
  `ingestion` container alone. NOT measured at the previous 7.4 GiB limit. ADR 0023.)
- [x] An ingestion workflow pulls dbt's `manifest.json` + `catalog.json` (dbt's own metadata
  artifacts, already produced by every `dbt build`) into OpenMetadata: every silver/gold
  model, its columns, and its lineage back through to `bronze.transactions`.
  (`make om-sync`: 11 tables registered — 2 bronze, 4 silver, 5 gold — and the dbt workflow
  ended `Errors: 0`, `Success %: 100.0`. `dbt docs generate` gives the artifacts, not
  `dbt build` alone: `catalog.json` needs a live connection. OpenMetadata 2.0.2 has no DuckDB
  connector and its dbt workflow doesn't create tables, so `scripts/openmetadata_sync.py`
  registers them — ADR 0023. Elementary's own models are excluded on purpose.)
- [x] Column-level lineage is real, not table-level only: `fact_transactions.amount` traces
  back to `bronze.transactions.amount`, through every model in between.
  (`bronze.transactions.amount -> silver.transactions.amount -> gold.fact_transactions.amount`
  from the live API. Not achievable as-is: dbt compiles the source to `delta_scan('s3://...')`,
  which OpenMetadata's SQL parser can't resolve, so the column chain stopped at silver; the
  ingested manifest copy names the source table instead. Known gap:
  `silver.transactions.occurrence_number` (a window function) has no column-level upstream.)
- [x] `docker-compose.yml` (or a dedicated `openmetadata/docker-compose.yml`) follows the same
  ephemeral, project-named, `down -v` pattern as the rest of this repo (ADR 0007) — this is
  optional infrastructure for local exploration, not something CI is expected to run per PR
  given the RAM cost above; note this explicitly rather than silently wiring it into CI.
  (`openmetadata/docker-compose.yml`, project `pfp-om`, named volumes, `make om-down` = `down -v`
  and nothing left behind; not referenced from `.github/` — stated in ADR 0023,
  `brain/components/ci.md` and SETUP.md.)

**Verification:**
- [x] Real RAM/CPU measurement pasted into the PR (`docker stats` or equivalent) alongside
  the `.wslconfig` limit it was measured against. (In the PR.)
- [x] A screenshot or `curl`'d API response showing `fact_transactions`' real column-level
  lineage in the running OpenMetadata instance. (`curl` of `/api/v1/lineage/getLineage` in
  the PR; also `make om-sync`'s own `check` step.)

**Dependencies:** T21, T23 · **Files:** `openmetadata/**`, `SETUP.md`, `brain/**` · **Size:** L
· **Skill:** ci-cd-and-automation

### T25: Phase 2 close — `docs/phase-2-close`

**Description:** Leave the phase presentable, mirroring T19's own close of Phase 1.

**Acceptance criteria:**
- [x] `README.md`: Phase 2's status row added to the existing progress table (not a rewrite —
  same pattern T19 used for Phase 1). (Its own "Phase 2" table beside Phase 1's, the badge,
  the architecture diagram extended, a synthetic quickstart, and an explicit "not yet
  validated against real data" note.)
- [x] Brain kept current: `brain/phases/phase-2.md` (new, mirrors `phase-1.md`'s shape),
  every new component/concept/decision note cross-linked. (Links, and anchors, in README,
  PROJECT.md, SETUP.md, docs/ and every `brain/**/*.md` checked with a script: no new
  broken ones.)
- [x] `PROJECT.md` checked against what was actually built vs. planned; any deviation noted.
  (A status block under Phase 2: Dagster covers bronze -> dbt, no "refresh" step yet;
  Elementary over Great Expectations; OpenMetadata over DataHub and why it's optional.)
- [x] Added beyond the list: `docs/ingesting-your-own-pdfs.md` (step-by-step for real
  statements, linked from README and SETUP.md), and `scripts/poc.py` now runs `dbt deps`
  first (test first) -- writing that walkthrough surfaced that `make poc` failed on any
  checkout that hadn't installed Elementary's package.

**Verification:**
- [x] Clone the repo into a clean folder and follow the README through to a materialized
  Dagster DAG with no missing steps. (Fresh `git clone` of this branch into `/tmp`, no
  `dbt/dbt_packages`, no manifest: README's quickstart commands verbatim -> `dagster asset
  materialize --select '*'` exit 0, `Done. PASS=127 WARN=0 ERROR=0`, 2m06s, and the gold
  query returned rows. One deviation, on purpose: `make poc-up` was replaced by an
  equivalent own compose project/port, because the real one would have reused the owner's
  running `pfp-poc-seaweedfs-1`.)

**Dependencies:** T20, T21, T22, T23, T24 · **Files:** `README.md`, `brain/**`, `PROJECT.md` ·
**Size:** S

### Phase 2 extension: PostgreSQL as dbt's store, then the dashboard (added 2026-09-19)

> Why and what: [ADR 0029](../brain/decisions/0029-dbt-stores-silver-and-gold-in-postgres.md). Phase 2
> was closed at T25; these tasks reopen it on purpose, because BI, the catalog and Dagster have to read
> what dbt builds while it builds (a DuckDB file has one writer). Order matters: each task leaves
> `develop` green and every task updates the brain notes it touches. Phase 3 (ML) starts after T33.

### T26: PostgreSQL service and the dbt connection — `infra/postgres-dbt-store`

**Description:** Add PostgreSQL to `docker-compose.yml` and point dbt-duckdb at it with `attach`
(`type: postgres`), so silver and gold are created there. DuckDB stays the engine reading bronze.

**Acceptance criteria:**
- [x] `postgres` service in `docker-compose.yml` (pinned image, data in a volume removed by `down -v`,
  bound to `127.0.0.1`), started by `make pg-up`; credentials only from `.env` (`PFP_PG_*`, added to
  `.env.example`). (Not by `make poc-up` yet: the default store flips in T27, so the real `pfp-poc`
  instance is not disturbed until then.)
- [x] `dbt/profiles.yml` has a `postgres` target (`--target postgres`, **opt-in**: the DuckDB file stays
  the default until T27, so `develop` stays green); `dbt build` creates every silver and gold model in
  Postgres, and the incremental `MERGE` and its purge behave as before (a second build changes
  nothing). Elementary is moved to its own DuckDB file on this target here, because the build cannot
  pass without it (the T28 task keeps the rest: `edr`, its tests and ADR 0022).
- [x] A read-only role `pfp_bi`, created when the volume is first made, that can `select` on `gold` only,
  including tables dbt recreates (tested).
- [x] `brain/decisions/0029-...md` (already written) confirmed against what was built; SETUP.md section 6
  updated; CI's `ephemeral-integration` brings up a Postgres and runs the new integration test.

**Verification:** `make pg-up` and the local S3, load the synthetic inbox, `dbt build --target postgres`:
every node passes (139/139) and a second build changes nothing; `tests/test_dbt_postgres_integration.py`
passes against a real Postgres and S3.

**Dependencies:** T25 · **Files:** `docker-compose.yml`, `dbt/profiles.yml`, `.env.example`, `Makefile`,
`SETUP.md`, `brain/**` · **Size:** M

### T27: Readers move from the DuckDB file to PostgreSQL — `refactor/readers-on-postgres`

**Description:** Everything that opened `dbt/pfp.duckdb` reads Postgres instead.

**Acceptance criteria:**
- [x] `scripts/poc.py` (transfer-match counts) reads Postgres; `make poc-up` starts it and `make poc`
  fails clearly without the `PFP_PG_*` variables; the Dagster module gives Elementary an absolute
  DuckDB path by default.
- [x] The integration tests that query the built tables read Postgres through one shared helper
  (`tests/pg_store.py`); each parallel pytest-xdist worker gets its own database, dropped and recreated
  with the test lake, so the parallel runner keeps working.
- [x] The default dbt target is Postgres (`PFP_DBT_TARGET`); `local` (the DuckDB file) stays selectable
  because CI's base-versus-PR data diff still needs it until T29. `PFP_DUCKDB_PATH` is now only that
  target's and `edr`'s (T28).

**Verification:** the whole integration suite passes with `-n 4` against a real Postgres and S3.

**Dependencies:** T26 · **Files:** `scripts/poc.py`, `orchestration/**`, `tests/**` · **Size:** L

### T28: Elementary on its own DuckDB file — `fix/elementary-own-duckdb`

**Description:** Elementary's view models and its end-of-run results upload do not work through the
Postgres attach. Give it a small DuckDB file of its own; its anomaly test still reads silver in Postgres.

**Acceptance criteria:**
- [x] Elementary's models and results land in a DuckDB file (`elementary` schema), not in Postgres (done
  in T26, which the Postgres target needed).
- [x] `volume_anomalies` still passes/warns as in T22 (its tests read the file), and `edr report` still
  renders: `edr` has its own profile on that file (integration test renders the report), and CI's `edr`
  step uses the same absolute path as dbt.
- [x] ADR 0022 (update section), `brain/components/elementary.md` and SETUP.md updated (where it lives now).

**Dependencies:** T27 · **Files:** `dbt/**`, `tests/test_elementary_anomaly_integration.py`,
`brain/**` · **Size:** M

### T29: CI on PostgreSQL — `ci/ephemeral-postgres`

**Description:** The ephemeral environment (ADR 0007) and the base-versus-PR data diff work on Postgres.

**Acceptance criteria:**
- [ ] `ephemeral-integration` brings up Postgres with SeaweedFS, runs the Dagster job and the integration
  tests, and tears both down (`down -v`).
- [ ] `scripts/data_diff.py` and `pr-data-diff` compare Postgres schemas (base and PR) instead of two
  DuckDB files; ADR 0014 updated.
- [ ] The job stays within its time budget (backlog, "CI speed").

**Dependencies:** T27, T28 · **Files:** `.github/workflows/ci.yml`, `scripts/data_diff.py`,
`brain/**` · **Size:** M

### T30: OpenMetadata reads PostgreSQL natively — `infra/openmetadata-postgres`

**Description:** Retire the custom DuckDB registration script now that OpenMetadata can read the tables
directly.

**Acceptance criteria:**
- [ ] OpenMetadata ingests the Postgres `silver` and `gold` schemas with its native connector and the
  dbt artifacts, and `fact_transactions.amount` still traces back to `bronze.transactions.amount`.
- [ ] `scripts/openmetadata_sync.py` is removed or reduced to what the connector does not cover; ADR 0023
  and `brain/components/openmetadata.md` updated; SETUP.md section 10 updated.

**Dependencies:** T26 · **Files:** `scripts/openmetadata_sync.py`, `docker-compose.openmetadata.yml`,
`SETUP.md`, `brain/**` · **Size:** M

### T31: Dagster shows the Postgres tables — `feat/dagster-postgres-assets`

**Description:** The Dagster asset graph shows bronze, each dbt model and where it is stored, so the
lake, dbt and the database are seen as one thing.

**Acceptance criteria:**
- [ ] The dbt assets carry their Postgres schema, table and row count as asset metadata after a run.
- [ ] The graph is documented (README/SETUP) with what to look at.

**Dependencies:** T27 · **Files:** `orchestration/**`, `brain/components/dagster.md` · **Size:** S

### T32: Superset over PostgreSQL — `infra/superset`

**Description:** Apache Superset (open source, no cost) in its own Compose stack, reading Postgres with the
read-only role, plus the first dashboards.

**Acceptance criteria:**
- [ ] `make bi-up` / `make bi-down` start and stop Superset (its metadata in its own database of the same
  Postgres); it is not started by `make poc-up`, like OpenMetadata.
- [ ] A Postgres database connection with the read-only role; dashboards as code (exported and committed):
  monthly cash flow (income and spending, no internal transfers), savings balance per month, and each
  fund's monthly return **with `closing_basis` beside the return**.
- [ ] The RAM it needs is measured against `.wslconfig` and written down (like T24).
- [ ] An ADR records Superset over Metabase and Streamlit; SETUP.md gets a section.

**Dependencies:** T26 · **Files:** `docker-compose.superset.yml`, `bi/**`, `Makefile`, `SETUP.md`,
`brain/**` · **Size:** L

### T33: Phase 2 re-close — `docs/phase-2-extension-close`

**Description:** Leave the extended phase presentable, as T25 did.

**Acceptance criteria:**
- [ ] README, PROJECT.md, `brain/phases/phase-2.md` and the architecture diagram reflect Postgres, Superset
  and the extension; nothing still says "embedded, no Postgres" as a current fact.
- [ ] A clean clone follows the README to a running dashboard.
- [ ] Links and anchors checked with a script.

**Dependencies:** T26-T32 · **Size:** S

### ✅ Final checkpoint (Phase 2, including the extension T26-T33)
- [ ] All criteria met · [ ] `develop → main` release PR "Phase 2 — Orchestration + Governance"
  · [ ] merged by Piero
