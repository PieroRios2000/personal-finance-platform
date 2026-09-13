---
type: decision
phase: 1
status: accepted
date: 2026-09-12
---

# ADR 0007: Ephemeral per-PR environments, not a fixed server

## Context

Unit tests with mocks don't catch everything a real platform would: a wrong S3 endpoint
config, a bucket that doesn't exist yet, a Delta write that silently produces the wrong
partitioning. Testing against the real platform (SeaweedFS S3, later dbt) needs somewhere
to run it, but this is a zero-cost, single-developer portfolio project (PROJECT.md): a
permanent shared server would sit idle most of the time, drift out of sync with the compose
file that's supposed to define it, and — with several PRs in flight — let one PR's data
corrupt another's if they shared the same bucket.

## Decision

Every PR that touches data gets its own temporary platform, created for the run and torn
down after, using the **same `docker-compose.yml`** locally and in CI:

- **A project name per environment** (`docker compose -p <name>`) isolates containers,
  networks and volumes: `pfp-poc` for a single local developer (T13, fixed — there's only
  one), `pfp-pr-<n>` per CI job (T17, parameterized by PR number).
- **Spin up** only if the change affects data (ADR 0008, written in T15):
  `docker compose -p <name> up -d --wait` (locally: `make poc-up`).
- **Run** ingestion and transformation against it — **synthetic** data in CI, so the jobs
  work the same for PRs from forks with no secrets involved; **real PDFs only locally**
  (`make poc`, T17), never in Git or CI.
- **Compare** the same run against the base branch and the PR's, publishing the difference
  (rows per model, schema, values) in the job summary — this is what a plain pass/fail test
  suite misses: the platform can stay "green" while quietly changing what the data looks
  like.
- **Always tear down**, even on failure (`if: always()` in CI): `docker compose -p <name>
  down -v` (locally: `make poc-down`), after saving logs and dbt's artifacts.

T13 lays the groundwork this ADR describes — the compose file itself, and `make
poc-up`/`poc-down` for the local, single-project case. T17 makes the environments genuinely
ephemeral per PR: a unique project name per CI job, synthetic ingestion, `dbt build`, and the
base-vs-PR comparison.

## Alternatives considered

- **A fixed shared dev/staging server**: cost (even a small always-on VM) and drift between
  what's deployed and what `docker-compose.yml` says; two PRs running at once would corrupt
  each other's data in the same bucket.
- **Testcontainers spun up inside the test process**: fine for isolated integration tests,
  but doesn't give a stable target to run `dbt build` against or a natural place to diff
  base vs. PR — and it would mean two different ways of describing the same platform (test
  code vs. compose file) instead of one.
- **No real platform at all, mocks only**: cheapest, but exactly what this ADR exists to
  avoid — a config mistake (endpoint, bucket, partitioning) would only surface once real data
  hits it.

## Consequences

- Every PR gets tested against the real platform it will actually run on, not a mock of it,
  with no fixed cost and no server to maintain.
- The project name is the whole isolation mechanism: forgetting it (or forgetting `-v` on
  teardown) leaks containers and volumes. T13's verification checks two projects running at
  once don't collide and that `poc-down` leaves nothing behind; T17's CI job additionally
  needs `if: always()` and a `timeout-minutes` so a stuck job can't leave its environment
  running forever (tracked as a risk in `tasks/plan.md`).
- These jobs use no secrets, which is what makes them safe to run on PRs from forks; cloud
  environments (Phase 4) are a different matter — those only run on branches of this repo,
  always get torn down, and carry an expiry.

## Related

- [ADR 0003: Local S3 with SeaweedFS](0003-local-s3-with-seaweedfs.md) — the compose file
  these environments run.
- ADR 0008: Impact-based CI (written in T15) — decides when the environment spins up at all.
- [Phase 1](../phases/phase-1.md) — "Ephemeral environments (ADR 0007)" section.
