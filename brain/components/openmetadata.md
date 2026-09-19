---
type: component
phase: 2
status: built
task: T24
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
| [`scripts/openmetadata_sync.py`](../../scripts/openmetadata_sync.py) `sync` | Registers the `pfp_duckdb` service, `pfp` database, `bronze`/`silver`/`gold` schemas and their tables (silver/gold from dbt's `catalog.json`, bronze from `lakehouse/bronze.py`'s pyarrow schemas), then writes `openmetadata/artifacts/`: a manifest copy with sources resolved to logical names, `catalog.json`, and the ingestion workflow config |
| `openmetadata/artifacts/` (gitignored) | What the ingestion container reads, mounted read-only at `/opt/pfp-artifacts`. Holds a short-lived admin token, so it is never committed |
| [`scripts/openmetadata_sync.py`](../../scripts/openmetadata_sync.py) `check` | Asks the running server for `gold.fact_transactions.amount`'s upstream lineage and exits 1 unless it reaches `bronze.transactions.amount` column by column |
| `make om-up` / `make om-sync` / `make om-down` | Start the stack under project `pfp-om`; run `dbt docs generate`, `sync`, the dbt ingestion workflow and `check`; tear down with `-v` and remove `artifacts/` |
| [`tests/test_openmetadata_sync.py`](../../tests/test_openmetadata_sync.py) | Unit tests for the transformations (type mapping, catalog and bronze tables, source resolution, workflow config, registration order, column-path walking); no server needed |

## How it fits together

```
dbt build -> dbt docs generate -> manifest.json + catalog.json
                                        |
                       openmetadata_sync sync ---- REST ---> OpenMetadata (tables, columns)
                                        |
                        artifacts/ (manifest copy, catalog, workflow config)
                                        |  read-only mount
                    metadata ingest (ingestion container) --> lineage
                                        |
                       openmetadata_sync check <--- REST --- column-level lineage
```

- **Why a script and not a DuckDB connector:** OpenMetadata 2.0.2 has none, and its dbt workflow
  only enriches tables that already exist. `sync` creates them, from dbt's `catalog.json` (which
  is DuckDB's own information schema).
- **Why the manifest is copied:** OpenMetadata parses each model's compiled SQL for column
  lineage, and `delta_scan('s3://...')` (ADR 0011) is not a table to it. In the copy, each
  source's `delta_scan(...)` is replaced by `"pfp"."bronze"."<name>"`, in `compiled_code` only.
  Without it the column chain stops at silver (verified against the real server).
- **Elementary's own models are not catalogued** (30-odd monitoring tables); dbt tests aren't
  ingested either.

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
