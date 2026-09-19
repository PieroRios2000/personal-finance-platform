---
type: decision
phase: 2
status: accepted
date: 2026-09-19
---

# ADR 0029: dbt stores silver and gold in PostgreSQL; DuckDB stays the engine

## Context

Until now `dbt build` wrote silver and gold into one DuckDB file (`dbt/pfp.duckdb`), and
[ADR 0002](0002-duckdb-and-delta-rs-before-spark.md) chose that with "no Postgres" as a Phase 1
virtue. Two things changed:

- The owner wants to look at the data in an open-source, zero-cost BI tool (Apache Superset), see
  the catalog (OpenMetadata) and the pipeline (Dagster) **related to each other**, and do so while the
  pipeline runs. A DuckDB file has a single writer: while dbt builds, nothing else can open it, and
  while a dashboard has it open, dbt cannot build.
- OpenMetadata 2.0.2 has no DuckDB connector, which forced a hand-written registration script
  ([ADR 0023](0023-openmetadata-catalog-and-column-lineage-from-dbt-artifacts.md)). It has a native
  PostgreSQL one.

A feasibility check on 2026-09-19 (a throwaway lake and Postgres, nothing kept) ran this project's
dbt models with **dbt-duckdb attaching PostgreSQL** as the target: every silver and gold model was
created there, `silver.transactions`' incremental `MERGE` with its `pre_hook` purge worked (rows
updated, inserted and deleted as expected), and the dbt tests passed. Two limits appeared: DuckDB
cannot rename views in an attached Postgres, so Elementary's view models fail unless materialized as
tables, and Elementary's end-of-run step that stores its results failed to copy one metrics table.

## Decision

- **dbt's target for silver and gold is PostgreSQL**, reached through dbt-duckdb's `attach`
  (`type: postgres`). DuckDB stays the **engine**: it reads bronze (Delta on S3) with `delta_scan()`
  ([ADR 0011](0011-delta-scan-as-a-dbt-source.md)) and writes the result into Postgres. Models keep
  their materializations; the incremental `MERGE` is kept.
- **Bronze does not move**: Delta Lake on SeaweedFS ([ADR 0003](0003-local-s3-with-seaweedfs.md)).
- **One Postgres instance, several databases**: the one dbt writes to, and later Superset's own
  metadata. BI tools get a **read-only role** on gold. Credentials come from `.env` (`PFP_PG_*`),
  like every other secret.
- **Elementary keeps its own small DuckDB file**, separate from Postgres (its view models and its
  results upload do not work through the attach). Its anomaly test still reads silver in Postgres.
- **The dashboard is Apache Superset**, in its own stack you start when you want to look at the data,
  reading Postgres. Streamlit stays reserved for the manual-data form ([Phase 5](../../PROJECT.md)).
- **The switch is gradual:** T26 adds Postgres as an opt-in dbt target (`--target postgres`) and keeps the
  DuckDB file as the default so every step leaves `develop` green; T27 flips the default when the readers
  move. Because a build on the Postgres target cannot pass with Elementary's models in Postgres, T26 already
  puts Elementary on its own DuckDB file for that target.
- **This is done inside Phase 2**, as extra tasks (T26 onward in
  [`tasks/todo-phase2.md`](../../tasks/todo-phase2.md)), before Phase 3 (ML).

## Alternatives considered

- **Keep DuckDB as the store and publish gold to Postgres after each build**: works with less change,
  but keeps two copies and a publish step, and leaves OpenMetadata and Dagster looking at a different
  store than dbt. Rejected by the owner in favour of one store.
- **Switch dbt to the native Postgres adapter (`dbt-postgres`)**: Postgres cannot read Delta from S3, so
  bronze would have to be loaded into Postgres first, losing the "dbt reads the lake directly" design.
- **Copy the DuckDB file for the dashboard**: stale between copies and fragile while copying.
- **ClickHouse, Trino, Spark**: far heavier than this data needs.
- **DuckLake** (DuckDB's newer lakehouse format with a Postgres catalog): allows concurrent access but is
  too recent for the part the owner looks at; can be revisited.

## Consequences

- **Postgres becomes a service `dbt build` needs** (free, light, in the same Docker Compose).
- **Everything that opened `dbt/pfp.duckdb` moves to Postgres**: `scripts/poc.py`, `scripts/data_diff.py`,
  `scripts/openmetadata_sync.py`, the Dagster wiring and about a dozen integration tests. Parallel test
  workers each need their own Postgres schema (the per-worker lake idea, again).
- **CI's ephemeral environment gets a Postgres**, and the base-versus-PR data diff compares Postgres
  schemas instead of two DuckDB files.
- **OpenMetadata reads Postgres with its native connector**, which retires the DuckDB workaround of
  ADR 0023 (its column-level lineage from dbt's artifacts stays).
- **The DBeaver/DuckDB instructions change** (SETUP.md sections 6 and 7): silver and gold are browsed in
  Postgres; bronze is still Delta.
- ADR 0002's "DuckDB + delta-rs before Spark" stands for the *engine*; its "embedded, no Postgres"
  storage half is superseded here. ADR 0023's DuckDB workaround is superseded by task T30.

## Related

- [Phase 2](../phases/phase-2.md)
- [dbt silver](../components/dbt-silver.md) and [dbt gold](../components/dbt-gold.md)
- [ADR 0002](0002-duckdb-and-delta-rs-before-spark.md), [ADR 0011](0011-delta-scan-as-a-dbt-source.md),
  [ADR 0023](0023-openmetadata-catalog-and-column-lineage-from-dbt-artifacts.md)
