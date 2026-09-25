---
type: decision
phase: 2
status: accepted
date: 2026-09-21
---

# ADR 0033: dev and prod environments on one machine, chosen by `PFP_ENV`

## Context

There was one stack, `pfp-poc`, run from whatever branch was checked out, holding the owner's real
data. A change to a dashboard, a model or the catalog therefore reached the place it was read
before anyone judged it, and `main` (the stable branch) had no environment of its own. The owner
asked for a DEV of Superset and of the catalog to evaluate a change before it goes to `main`, with
**real data in DEV** (local) and **artificial data in prod**, so anyone can see what the dashboard
looks like before loading their own information.

## Decision

`PFP_ENV` (default `poc`) picks the **Compose project, the env file and the ports**; every
environment has its own volumes, Postgres, Superset and catalog, so nothing is shared.

| `PFP_ENV` | Project | Env file | Ports | Data | Code |
|---|---|---|---|---|---|
| `poc` (default) | `pfp-poc` | `.env` | as in `.env.example` | the current stack, unchanged | any |
| `dev` | `pfp-dev` | `.env.dev` | +100 | **real** (`make ingest`) | develop and feature branches |
| `prod` | `pfp-prod` | `.env.prod` | +200 | **artificial** (`make demo`) | `main` only |

- **The flow:** change on a branch, `make up PFP_ENV=dev` from that checkout, look at it with the real
  data; when it is right, merge to `develop` and then to `main`; start prod from a checkout of `main`
  (`git worktree add ../pfp-prod main`, then `make up PFP_ENV=prod` there). Prod never runs anything that
  is not on `main`.
- **Guards, not conventions:** `make env-guard` (run by `up` and `demo`) refuses prod on any branch but
  `main` and dev on `main` (`FORCE=1` overrides); `make guard-user` refuses `make demo` unless the env
  file's `PFP_USER` is `demo`, and `make ingest` when it is `demo`, so a real dashboard never gets demo rows
  and the demo never gets real ones.
- **`make env PFP_ENV=dev`** writes that environment's file: generated secrets, ports shifted together
  (the S3 endpoint URL stays in step), the user name (`USER_NAME=...`; `demo` for prod).
  Any other name works with its own `PORT_OFFSET` (used to test this change with two throwaway
  environments at once).
- `make ingest` and `make build` wrap `pfp ingest` and `dbt build` with the environment's variables, so
  nothing is sourced by hand and the wrong environment is not touched by a stale shell.
- **The catalog's artifacts are per environment** (`openmetadata/artifacts/<env>/`): they hold a token and
  the Postgres password.
- **Names:** every `docker compose` call still goes through `$(PFP)` and the project name is derived once
  from `PFP_ENV`; a test forbids a literal name (the lesson of the 2026-09-21 incident).

## Alternatives considered

- **Branch-named projects (`pfp-<branch>`):** automatic, but ports and data would multiply with every
  feature branch and nothing says which one is "the real data". Two named environments are a decision.
- **One database with two schemas per environment:** dev and prod would share a Postgres, Superset and its
  failures; a bad dev migration could take prod down. Separate projects share nothing.
- **A second machine or a cloud dev:** the real data must stay on the owner's machine (ADR 0004); cloud
  environments are Phase 4.

## Consequences

- A second (or third) stack costs its RAM: Superset about 0.35 GiB, Postgres and S3 little; OpenMetadata
  4.6 GiB each, so run the catalog in one environment at a time.
- Moving the owner's current stack to `dev` means re-ingesting the archived PDFs into it
  ([runbook](../../docs/runbook-rebuild-from-archive.md), with `PFP_ENV=dev`); `pfp-poc` keeps working
  untouched until then.
- CI is unchanged (it names its own project and never sets `PFP_ENV`).

## Related

[ADR 0032](0032-one-compose-project-one-command.md) (one Compose project),
[ADR 0004](0004-real-pdfs-never-leave-your-machine.md), [ADR 0007](0007-ephemeral-per-pr-environments.md),
the [incident](../../docs/incidents/2026-09-21-poc-down-wiped-the-real-stack.md).
