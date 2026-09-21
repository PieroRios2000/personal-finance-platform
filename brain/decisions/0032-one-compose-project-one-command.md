---
type: decision
phase: 2
status: accepted
date: 2026-09-21
---

# ADR 0032: the whole platform is one Compose project with one command

## Context

Storage and Postgres ran as project `pfp-poc`, Superset as `pfp-bi` and OpenMetadata as `pfp-om`:
three groups in Docker Desktop and three commands to start, in the right order, each joining the
Postgres network of another project through an external network. The owner wanted to start everything
at once, and see it as one thing.

## Decision

**One Compose project, `pfp-poc`, and one command.** The root `docker-compose.yml` `include`s
`bi/docker-compose.yml` and `openmetadata/docker-compose.yml`; their services sit behind the `bi` and
`catalog` **profiles**.

- `make up` = storage + Postgres + Superset; `make up-catalog` adds OpenMetadata; `make status` lists
  what runs and the URLs; `make down` stops all of it keeping the data; `make poc-down` deletes the data
  as before.
- **One network:** no external `PFP_NETWORK` trick any more. Superset's setup and OpenMetadata's
  connector reach Postgres as `postgres:5432` because they are in the same project; `bi-init` waits for
  Postgres to be healthy (`depends_on`).
- **CI and `make poc-up` are unchanged:** they name `seaweedfs postgres`, and profile services are not
  started unless a profile is on.
- **The project name did not change**, so an existing install keeps its lake and Postgres volumes.
  `make up` stops the old `pfp-bi` / `pfp-om` projects first (their ports would clash).
- `include` reads every file even for a stopped profile, so the included files cannot use required-
  variable interpolation (it would break projects that do not use them): `make bi-check` verifies the
  Superset variables before `make up`. OpenMetadata's Postgres volume is renamed `om-postgres-data` (it
  clashed with PFP's `postgres-data`).

## Alternatives considered

- **One container:** Postgres, S3, Superset and the catalog are different processes with different
  lifecycles (and OpenMetadata alone is five containers); a single container would be a worse Docker
  image, not a simpler one. One project gives the "one thing" without it.
- **A `make up` that runs three `docker compose` projects:** one command, but still three groups and the
  external-network coupling.
- **Merging the files into one:** one 700-line file; `include` keeps each stack in its own file.

## Consequences

- Docker Desktop shows one stack, `pfp-poc`, with every container in it.
- `make om-down` removes only the catalog and its volumes; `make bi-down` only Superset.
- Standalone use of `bi/docker-compose.yml` or the OpenMetadata file (`-f`) no longer works: they depend
  on Postgres in the root file. That was already the practice.

## Related

[ADR 0007](0007-ephemeral-per-pr-environments.md), [ADR 0023](0023-openmetadata-catalog-and-column-lineage-from-dbt-artifacts.md),
[ADR 0029](0029-dbt-stores-silver-and-gold-in-postgres.md), [ADR 0030](0030-superset-for-dashboards-over-the-read-only-role.md).
