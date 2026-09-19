---
type: phase
phase: 2
status: extended
---

# Phase 2 — Orchestration + Governance (closed 2026-09-18, extended 2026-09-19)

The same PDFs now flow through one orchestrated DAG (Dagster), silver is an incremental `MERGE`
keyed on each transaction's business key, gold is a star schema, Elementary watches silver for
anomalies, and OpenMetadata (optional, local) shows column-level lineage back to bronze. Plan in
[tasks/plan-phase2.md](../../tasks/plan-phase2.md), tasks in
[tasks/todo-phase2.md](../../tasks/todo-phase2.md).

## Status

| Task | What | Status |
|---|---|---|
| T20 | Business-key `MERGE` in silver + the balance-reconciliation dbt test | done (#68) — [ADR 0018](../decisions/0018-incremental-merge-business-key-occurrence-number.md) |
| T21 | Dagster orchestration: bronze asset + every dbt node as one DAG; CI runs the pipeline through it | done (#71) — [ADR 0021](../decisions/0021-ci-invokes-the-dagster-pipeline.md) |
| T22 | Elementary: dbt package, a row-count anomaly test on silver (warn-mode), local report | done (#72) — [ADR 0022](../decisions/0022-elementary-anomaly-detection-and-warn-mode.md) |
| T23 | Gold star schema: `fact_transactions` + four dimensions, `flow_type` | done (#70) — [ADR 0020](../decisions/0020-gold-star-schema-flow-type-and-dim-account-grain.md) |
| T24 | OpenMetadata catalog and column-level lineage (optional, not in CI) | done (#73) — [ADR 0023](../decisions/0023-openmetadata-catalog-and-column-lineage-from-dbt-artifacts.md) |
| T25 | Phase close: README, this note, PROJECT.md, the walkthrough for real PDFs, `make poc` installs dbt packages | done |

### Extension: PostgreSQL as dbt's store, then the dashboard (T26–T33, planned)

Added after the phase closed, on the owner's decision: BI, the catalog and Dagster must read what dbt
builds *while it builds*, and a DuckDB file has a single writer. dbt keeps DuckDB as the **engine** (it
reads bronze from the lake) and stores silver and gold in **PostgreSQL**; Apache Superset then reads it.
Decision, feasibility check and consequences: [ADR 0029](../decisions/0029-dbt-stores-silver-and-gold-in-postgres.md);
acceptance criteria in [`tasks/todo-phase2.md`](../../tasks/todo-phase2.md). Phase 3 (ML) starts after T33.

| Task | What | Status |
|---|---|---|
| T26 | PostgreSQL service and the dbt connection (opt-in `--target postgres`; read-only BI role; Elementary on its own file for this target) | done — [ADR 0029](../decisions/0029-dbt-stores-silver-and-gold-in-postgres.md) |
| T27 | Scripts, Dagster wiring and tests read PostgreSQL instead of the DuckDB file | planned |
| T28 | Elementary keeps its own small DuckDB file | planned |
| T29 | CI's ephemeral environment and the PR data diff on PostgreSQL | planned |
| T30 | OpenMetadata reads PostgreSQL natively (retires the DuckDB workaround of ADR 0023) | planned |
| T31 | Dagster shows where each model is stored | planned |
| T32 | Superset over a read-only role on gold: cash flow, savings, each fund's monthly return | planned |
| T33 | Phase 2 re-close | planned |

Until each task lands, the notes below describe the DuckDB-file version; each task updates the notes it
touches.

Also integrated during the phase: `ephemeral-integration` made genuinely required through an
always-run gate job (#69, [ADR 0019](../decisions/0019-ephemeral-integration-required-via-gate-job.md)),
after Piero saw a PR could be approved without it.

**Closing this phase (T25, 2026-09-18).** Every task is built, tested with synthetic data and
merged, and a clean clone follows the README's quickstart through to a materialized Dagster DAG
(evidence in T25's PR). Open items, stated plainly:

- **Real-data validation is still the owner's step** (ADR 0004), as at the close of Phase 1:
  nothing in this phase has run against real Scotiabank statements.
  [`docs/ingesting-your-own-pdfs.md`](../../docs/ingesting-your-own-pdfs.md) is the walkthrough.
  Writing it turned up one real gap that only a real run would have hit: `make poc` ran
  `dbt build` without `dbt deps`, so it failed on any checkout that hadn't installed
  Elementary's package. Fixed in T25 (`scripts/poc.py`, test first).
  **Update (2026-09-19, first real run):** BCP parsed 60/60; real Scotiabank statements
  corrected the card parser (title-case `Saldo Anterior`, a stray `(abc:12)` tag after some
  amounts, and the last `Total` being the declared closing balance) and turned out to include a
  second layout, a savings account, now parsed by `scotiabank_account.py`. See
  [the parser note](../components/scotiabank-parser.md).
  With all 85 real statements in one lake, `dbt build` then failed twice for reasons the synthetic data could
  not show, both fixed: the continuity test now checks one statement per account and month instead of counting days, and the balance
  reconciliation matches movements to their statement by file, not by date. Final run: every node passes.
- **The numeric rules are still in warn mode** — CONSTRAINTS.md's switch date is 2026-09-26,
  not yet reached; flipping `continue-on-error` and the `-`/`||true` markers is a two-line
  change once it is.
- **OpenMetadata is not in CI and was measured on a 14.88 GiB Docker allocation** (peak
  4.76–4.81 GiB and 457–554% CPU during ingestion, in two independent runs); it was never measured at the earlier 7.4 GiB limit.
  Its column-level lineage has two documented gaps (`silver.transactions.occurrence_number`
  has only a table-level edge; the manifest handed to it is a rewritten copy) — ADR 0023.
- **Silver and gold live in `dbt/pfp.duckdb`, a local DuckDB file; only bronze is Delta on S3.**
  The layers exist; the storage isn't uniform. Moving them onto the lake is not planned here.
- **No `dim_category`, no dashboard, no ML.** Categories and ML are Phase 3, the dashboard
  Phase 5 ([PROJECT.md](../../PROJECT.md)).

## Components

- [dbt silver](../components/dbt-silver.md) — extended (T20): incremental `MERGE` on the business key, `purge_reprocessed_files()` so a backfill can change a row's own key, and the balance-reconciliation test.
- [dbt gold](../components/dbt-gold.md) — built (T23): `fact_transactions`, `dim_date`, `dim_account`, `dim_bank`, `dim_user`, natural keys, `flow_type`.
- [dagster](../components/dagster.md) — built (T21): the `bronze` asset, the dbt project as assets, `DAGSTER_MODULE_NAME`, and the gotchas found running it for real.
- [Elementary](../components/elementary.md) — built (T22): the dbt package, the `elementary` profile `edr` needs, warn-mode.
- [OpenMetadata](../components/openmetadata.md) — built (T24): the optional local stack and `scripts/openmetadata_sync.py`.
- [CI](../components/ci.md) — extended: `ephemeral-integration` runs the Dagster path, `dbt deps` in the places that need it, Elementary steps in warn-mode.

## Decisions

| ADR | Decision | Note |
|---|---|---|
| 0018 | Incremental `MERGE`; business key with an occurrence number scoped to one source file | [ADR 0018](../decisions/0018-incremental-merge-business-key-occurrence-number.md) |
| 0019 | `ephemeral-integration` required via an always-run gate job | [ADR 0019](../decisions/0019-ephemeral-integration-required-via-gate-job.md) |
| 0020 | Gold star schema: natural keys, `flow_type`, `dim_account`'s grain | [ADR 0020](../decisions/0020-gold-star-schema-flow-type-and-dim-account-grain.md) |
| 0021 | CI invokes the pipeline through Dagster | [ADR 0021](../decisions/0021-ci-invokes-the-dagster-pipeline.md) |
| 0022 | Elementary's anomaly test, warn-mode scoping, where `dbt deps` had to go | [ADR 0022](../decisions/0022-elementary-anomaly-detection-and-warn-mode.md) |
| 0023 | OpenMetadata catalog and column lineage from dbt artifacts | [ADR 0023](../decisions/0023-openmetadata-catalog-and-column-lineage-from-dbt-artifacts.md) |
| 0024 | A regenerated PDF with identical content is a duplicate, not `_v2` (found on a real inbox, after the phase closed) | [ADR 0024](../decisions/0024-regenerated-pdfs-with-identical-content-are-duplicates.md) |

## Concepts

- [Business key](../concepts/business-key.md) — its open question (two identical same-day purchases) was resolved by T20.
- [Medallion architecture](../concepts/medallion.md) — gold now exists.

## Related

- [Phase 1](phase-1.md)
- [Walkthrough: ingesting your own PDFs](../../docs/ingesting-your-own-pdfs.md)
