---
type: component
phase: 2
status: built
task: T30
---

# OpenMetadata

A browsable catalog and column-level lineage over the dbt project: every bronze, silver and
gold table with its typed columns, and how each gold column traces back to bronze. Optional,
local-exploration infrastructure — **CI never runs it** (about 4.6 GiB of containers at idle).
Design decisions and their alternatives in
[ADR 0023](../decisions/0023-openmetadata-catalog-and-column-lineage-from-dbt-artifacts.md).

## Pieces

| Piece | What it does |
|---|---|
| [`openmetadata/docker-compose.yml`](../../openmetadata/docker-compose.yml) | OpenMetadata 2.0.2 (PostgreSQL variant): `postgresql`, `elasticsearch` 9.3.0, a one-shot `execute-migrate-all`, `openmetadata-server` (UI/API on `localhost:8585`) and `ingestion` (Airflow plus the `metadata` CLI). Condensed from the official release file; named volumes only, so `down -v` leaves nothing; only 8585 published |
| [`scripts/openmetadata_sync.py`](../../scripts/openmetadata_sync.py) `sync` | Registers the `pfp_postgres` service (native Postgres connection), the `pfp` database and the **bronze** schema and tables (from `lakehouse/bronze.py`'s pyarrow schemas: Delta tables the connector cannot see), then writes `openmetadata/artifacts/`: the Postgres connector's workflow config, a manifest copy with sources resolved to logical names, `catalog.json`, and the dbt workflow config |
| Native Postgres connector | `metadata ingest -c postgres-workflow.yaml` reads the `silver` and `gold` schemas (tables, typed columns) straight from PFP's Postgres; the `ingestion` container joins the Postgres network (`pfp-poc_default`, `PFP_NETWORK`) |
| `openmetadata/artifacts/` (gitignored) | What the ingestion container reads, mounted read-only at `/opt/pfp-artifacts`. Holds a short-lived admin token and the Postgres password, so it is never committed |
| [`scripts/openmetadata_sync.py`](../../scripts/openmetadata_sync.py) `check` | Asks the running server for `gold.fact_transactions.amount`'s upstream lineage and exits 1 unless it reaches `bronze.transactions.amount` column by column |
| `make om-up` / `make om-sync` / `make om-down` | Start the stack under project `pfp-om` (needs `make poc-up` first); run `dbt docs generate`, `sync`, the Postgres and dbt ingestion workflows and `check`; tear down with `-v` and remove `artifacts/` |
| [`tests/test_openmetadata_sync.py`](../../tests/test_openmetadata_sync.py) | Unit tests for the transformations (type mapping, catalog and bronze tables, source resolution, workflow config, registration order, column-path walking); no server needed |

## How it fits together

```
dbt build -> dbt docs generate -> manifest.json + catalog.json
                                        |
                 openmetadata_sync sync ---- REST ---> OpenMetadata (service, bronze tables)
                                        |
                  artifacts/ (workflow configs, manifest copy, catalog)
                                        |  read-only mount
   metadata ingest postgres (ingestion container) --> silver, gold tables (native connector)
   metadata ingest dbt      (ingestion container) --> lineage
                                        |
                       openmetadata_sync check <--- REST --- column-level lineage
```

- **Why a script for bronze:** silver and gold are in Postgres, so the native connector catalogues
  them (T30, before that a DuckDB script did). Bronze is Delta on S3, which no connector reads,
  and the dbt workflow only enriches tables that already exist, so `sync` creates bronze's tables.
- **Why the manifest is copied:** OpenMetadata parses each model's compiled SQL for column
  lineage, and `delta_scan('s3://...')` (ADR 0011) is not a table to it. In the copy, each
  source's `delta_scan(...)` is replaced by `"pfp"."bronze"."<name>"`, in `compiled_code` only.
  Without it the column chain stops at silver (verified against the real server).
- **Elementary's own models are not catalogued** (they live in a separate DuckDB file, not in
  Postgres); dbt tests aren't ingested either.

## What lineage shows, and what it doesn't

Every column of `gold.fact_transactions`, `gold.dim_account`, `gold.dim_date` and
`silver.transactions` traces to a bronze column, except `occurrence_number` (a
`row_number() over (...)`: no column lineage past silver, table-level only). Multi-input
expressions list every input column. It needs a built lake and a fresh `dbt docs generate`.
See the ADR for the details and the measured RAM/CPU.

## Related

- [ADR 0023](../decisions/0023-openmetadata-catalog-and-column-lineage-from-dbt-artifacts.md) —
  every design call, the alternatives, and the resource measurements.
- [dbt silver](dbt-silver.md) and [dbt gold](dbt-gold.md) — the models it catalogues.
- [Lakehouse](lakehouse.md) — where bronze's schemas come from.
- [Elementary](elementary.md) — excluded from the catalog.
- [CI](ci.md) — does not run this, on purpose.
- [ADR 0007](../decisions/0007-ephemeral-per-pr-environments.md) and
  [ADR 0011](../decisions/0011-delta-scan-as-a-dbt-source.md)
