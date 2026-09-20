---
type: decision
phase: 2
status: accepted
date: 2026-09-20
---

# ADR 0030: Apache Superset for dashboards, over the read-only role, with dashboards as code

## Context

The owner wants to see the data in an open-source, zero-cost BI tool, not Power BI. With silver and
gold in PostgreSQL ([ADR 0029](0029-dbt-stores-silver-and-gold-in-postgres.md)) and a read-only role
that can read `gold` and nothing else (`pfp_bi`), any Postgres-capable BI tool can connect. The first
dashboards are monthly cash flow (income and spending, without internal transfers), the savings
balance per month, and each fund's monthly return next to how the month was closed.

## Decision

**Apache Superset 5.0.0**, in its own optional Compose project (`bi/docker-compose.yml`, project
`pfp-bi`, `make bi-up` / `make bi-down`), never started by `make poc-up` and never by CI.

- **Read-only by construction.** Superset's data connection is the `pfp_bi` role: `gold` only, and
  read-only at session level, so a chart or a SQL Lab query cannot read `silver` or write anything
  (verified: `select` on `silver.transactions` as `pfp_bi` is denied).
- **Its own metadata database.** Users, charts and dashboards live in a `superset` database of the same
  Postgres, owned by a `superset` role that `bi/init-metadata.sh` creates (idempotently, on every
  `make bi-up`, so it also works on a volume created before Superset existed). Nothing of Superset's is
  ever in `pfp`, where dbt writes.
- **Dashboards as code.** `bi/assets/` is Superset's own export format (YAML), committed. `bi/start.sh`
  imports it on start (`superset import-directory`), so a clean clone gets the dashboards with no clicks.
  The connection's password is masked in the export and filled in at start from the environment, never
  written to the repository. `bi/build_dashboards.py` (`make bi-export`) is how the export was authored,
  through Superset's REST API, and is how it is changed.
- **One new gold model** for the savings chart: `gold.fct_account_balance_monthly`, the closing balance
  each statement declares, per account, currency and month. Nothing recomputes a balance.
- **The return table shows `closing_basis` right beside `return_pct`**, so a return is never read without
  knowing whether the month closed at a real valuation or only at the last movement (ADR 0028).
- **Currencies are never added.** Every chart splits by currency; there is no FX before Phase 6.
- **Tiny footprint:** measured 335 MiB idle and after loading every chart (one container, two gunicorn
  workers, the default in-memory cache, no Redis or Celery); the image is 3.7 GB on disk.

## Alternatives considered

- **Metabase:** simpler to start, but its dashboards are not files: they live in its application
  database, so "dashboards as code" would be a database dump, not a reviewable diff. Superset's export is
  YAML.
- **Streamlit (or another Python app):** total control, but it is code to maintain, not a BI tool; the
  point here is exploring data with a tool an analytics team would actually use.
- **Superset in the same Compose file as Postgres:** would start with `make poc-up` and cost RAM for
  everyone; it is optional exploration, like the catalog.
- **Redis + Celery workers:** needed for alerts, reports and async queries; none is used here.

## Consequences

- `make bi-up` needs `make poc-up` first (the Postgres it reads) and three secrets in `.env`
  (`PFP_BI_DB_PASSWORD`, `PFP_BI_ADMIN_PASSWORD`, `PFP_BI_SECRET_KEY`).
- Run `make bi-down` before `make poc-down`: while Superset is attached, Docker cannot remove the
  Postgres network.
- Changing a dashboard means editing it (in Superset or `bi/build_dashboards.py`) and re-exporting; the
  YAML is the reviewed artifact.
- The chart definitions are checked against real data when authored (each reads at least one row through
  the read-only role); how they look is checked by opening them.

## Related

[ADR 0029](0029-dbt-stores-silver-and-gold-in-postgres.md) (Postgres store and the `pfp_bi` role),
[ADR 0028](0028-investment-return-is-modified-dietz-per-fund-and-month.md) (`closing_basis`),
[ADR 0007](0007-ephemeral-per-pr-environments.md) (optional stacks stay out of CI).
