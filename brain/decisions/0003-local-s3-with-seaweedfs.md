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

SeaweedFS with its S3 gateway (Apache 2.0 license), run via docker compose
(`docker-compose.yml`, T13).

**Final configuration:**

- **Image:** `chrislusf/seaweedfs:4.46`, pinned (verified pullable on Docker Hub before
  committing to it; `latest` and `dev` exist too, but a moving tag would make the
  environment non-reproducible between runs).
- **Process:** a single `server -s3` process (master + volume + filer + S3 gateway together)
  — the simplest topology for a laptop; no need for separate master/volume/filer containers
  at this scale.
- **Credentials:** only from `.env` (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`,
  already in `.env.example` since T6), passed as environment variables into the container.
  `weed`'s S3 gateway reads them itself as a fallback admin identity when no `config.json`
  is given — no credential value is ever written into `docker-compose.yml`.
- **Bucket:** `lakehouse`, created on startup by a one-shot `bucket-init` service that waits
  for the S3 gateway's healthcheck, then runs `weed shell` (`s3.bucket.create -name
  lakehouse`) against the filer — no S3 credentials needed for that step, and re-running it
  is a no-op. It runs via `docker compose run --rm`, outside `up --wait`'s tracked set:
  `up --wait` treats any container exiting, even with code 0, as a failure unless another
  long-running service depends on it ([docker/compose#10596](https://github.com/docker/compose/issues/10596)).
- **Host port:** `${SEAWEEDFS_S3_PORT:-8333}`, matching `AWS_ENDPOINT_URL` in `.env.example`;
  no fixed `container_name` anywhere, so Compose's own `-p <project>` naming keeps
  several instances (e.g. two PRs' environments) from colliding.
- **Healthcheck:** `curl` against the S3 port with no `-f` — any HTTP response (even a 403
  for an unsigned request) proves the gateway is listening and handling requests; `-f`
  would misread that 403 as a failed check. SeaweedFS's S3 gateway has no dedicated
  `/healthz`/`/status` route usable for this (see [seaweedfs#8243](https://github.com/seaweedfs/seaweedfs/issues/8243)).

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
- [ADR 0007: Ephemeral per-PR environments](0007-ephemeral-per-pr-environments.md) — what runs this compose file, and when.
- [Medallion architecture](../concepts/medallion.md)
- [Phase 1](../phases/phase-1.md)
