---
type: decision
phase: 1
status: accepted
date: 2026-09-12
---

# ADR 0003: Local S3 with SeaweedFS instead of MinIO

## Context

The lake needs S3-compatible storage locally, to work the same way it would against a cloud
object store. PROJECT.md proposed MinIO, but MinIO Community stopped publishing images in
October 2025, moved to maintenance mode in December 2025, and its repo was archived in 2026:
it no longer gets security patches.

## Decision

SeaweedFS with its S3 gateway (Apache 2.0 license), run via docker compose. The final
configuration (image tag, credentials and bucket) gets pinned in T13, which updates this ADR.

## Alternatives considered

- **Stay on MinIO Community**: the last image would be left without security patches.
- **A local folder without S3**: loses parity with an object store and the endpoint
  configuration the pipeline will need in the cloud.
- **Ceph (RADOS Gateway)**: full-featured, but heavy for a laptop.

## Consequences

- The pipeline speaks standard S3: switching servers (SeaweedFS, another local S3, or the
  cloud in Phase 4) means changing the endpoint and credentials in `.env`.
- The same compose file serves the ephemeral per-PR environments, locally and in CI (ADR 0007, T13).

## Related

- [ADR 0002: DuckDB + delta-rs](0002-duckdb-and-delta-rs-before-spark.md) — what's stored here.
- [Medallion architecture](../concepts/medallion.md)
- [Phase 1](../phases/phase-1.md)
