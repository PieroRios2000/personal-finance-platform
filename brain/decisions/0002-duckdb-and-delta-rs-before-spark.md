---
type: decision
phase: 1
status: accepted
date: 2026-09-12
---

# ADR 0002: DuckDB + delta-rs before Spark

## Context

PROJECT.md proposes PySpark, DuckDB and Polars. In Phase 1 the volume is personal bank
statements (thousands of rows), WSL has 7 GB of RAM, and what the project needs from the lake
is the Delta format: ACID transactions and MERGE for deduplication.

## Decision

- Write to Delta Lake with **delta-rs** (the `deltalake` library), no JVM.
- Read and transform with **DuckDB**: dbt-duckdb reads Delta from the local S3.
- Spark comes in when there's a measurable reason for it (volume or a demo), on the same Delta tables.

## Alternatives considered

- **PySpark + delta-spark**: needs a JVM and a fair amount of memory; overkill for thousands of
  rows on a laptop.
- **Polars**: would be a third engine for the same job, with nothing DuckDB doesn't already cover here.
- **Loose Parquet files**: no transactions or MERGE, so business-key deduplication would be fragile.

## Consequences

- A light, fast stack, both locally and in CI.
- Since the format is Delta, adding Spark later doesn't require migrating data.
- delta-rs over S3 has no locking between writers: Phase 1 has a single writer; documented in
  ADR 0006 (T14) and revisited in Phase 2 with Dagster.
- Reading Delta on the local S3 from DuckDB requires configuring the endpoint, path-style
  access and SSL: T16 starts with a minimal test before modeling anything.

## Related

- [Medallion architecture](../concepts/medallion.md) — the layers stored in Delta.
- [Business key](../concepts/business-key.md) — the deduplication that needs MERGE.
- [ADR 0003: SeaweedFS](0003-local-s3-with-seaweedfs.md) — where the tables live.
- [Phase 1](../phases/phase-1.md)

## Update 2026-09-19

The engine choice stands (DuckDB + delta-rs before Spark). The *storage* half, "embedded, no Postgres", is superseded by [ADR 0029](0029-dbt-stores-silver-and-gold-in-postgres.md): dbt now writes silver and gold to PostgreSQL through DuckDB's attach, so BI tools, the catalog and Dagster can read while it builds.
