---
type: decision
phase: 2
status: accepted
date: 2026-09-18
---

# ADR 0023: OpenMetadata as the catalog, fed from dbt's own artifacts, outside CI

## Context

T24 asks for a browsable catalog and column-level lineage, ingested from dbt's `manifest.json`
and `catalog.json` and DuckDB's catalog, with `gold.fact_transactions.amount` traceable back to
`bronze.transactions.amount`. OpenMetadata was chosen over DataHub for a lighter footprint
(`tasks/plan-phase2.md`); this ADR records what building it actually decided, because three of
the assumptions behind the plan did not hold up against the real 2.0.2 stack:

- there is **no DuckDB connector** in OpenMetadata 2.0.2 (checked in the `ingestion` image:
  `metadata/ingestion/source/database/` has `sqlite`, `deltalake`, `postgres`... but no
  `duckdb`);
- OpenMetadata's dbt workflow only **enriches tables that already exist** in the catalog; it
  never creates them;
- bronze is not a DuckDB table (ADR 0011: `delta_scan()` on an `external_location`), so dbt's
  `catalog.json` has no bronze entries and dbt's compiled SQL never names bronze as a table.

## Decision

**OpenMetadata 2.0.2, PostgreSQL variant, versions pinned exactly** in
[`openmetadata/docker-compose.yml`](../../openmetadata/docker-compose.yml):
`docker.getcollate.io/openmetadata/{postgresql,server,ingestion}:2.0.2` and
`docker.elastic.co/elasticsearch/elasticsearch:9.3.0` (the versions of the official
`2.0.2-release` `docker-compose-postgres.yml`). The file is condensed from that 559-line
release file, not copied: the extra ~450 lines restate the server's own defaults (OIDC, SAML,
SMTP, HSTS, secrets managers), which the image applies by itself. It follows ADR 0007's
pattern: fixed project name `pfp-om` (distinct from `pfp-poc`), `down -v` leaves nothing
(`make om-up` / `make om-down`). Two deliberate differences from upstream:

- **Named volumes only.** Upstream bind-mounts `./docker-volume/db-data-postgres`, a directory
  the container's postgres user creates; after `down -v`, `rm -rf` of it fails with
  "Permission denied". A named volume is removed by `down -v` (verified: no `pfp-om_*` volume,
  no `openmetadata/artifacts` left after `make om-down`).
- **Only 8585 (UI and API) is published**, not 5432/9200/9300/8586/8080. Nothing here needs
  them from the host, and 5432 collides with any Postgres already on the machine.

**Tables reach the catalog through a small script, not a connector.**
[`scripts/openmetadata_sync.py`](../../scripts/openmetadata_sync.py) `sync` creates a
`CustomDatabase` service (`pfp_duckdb`) and, over the REST API, its database (`pfp`),
schemas (`bronze`, `silver`, `gold`) and tables with typed columns. Silver and gold come from
dbt's `catalog.json` — which is DuckDB's own information schema, read by `dbt docs generate`
through the live connection, i.e. "DuckDB's catalog" without a connector. Bronze comes from
the pyarrow schemas `lakehouse/bronze.py` writes with, converted to DuckDB types by DuckDB
itself (`duckdb.from_arrow`), which are exactly the types `delta_scan()` hands to dbt. A type
the mapping doesn't know raises instead of being guessed.

**Source resolution in the manifest copy.** OpenMetadata derives column lineage by parsing
each model's `compiled_code`. dbt compiles `source('bronze','transactions')` to
`delta_scan('s3://.../bronze/transactions')`, a table function the parser cannot resolve to a
table. `sync` therefore writes a copy of `manifest.json` in which each source's
`relation_name` is replaced, inside `compiled_code` only, by `"pfp"."bronze"."transactions"`.
The lineage is still computed by OpenMetadata's own parser; the copy just makes the SQL name
the logical table the source already has in the catalog. Measured both ways against the real
server: with the untouched manifest, `check` fails (column paths stop at
`silver.transactions.amount -> gold.fact_transactions.amount`; table-level bronze edges exist
from `depends_on`, column-level ones don't); with the resolved copy, the chain reaches
bronze.

**The dbt workflow runs with `metadata ingest -c ...` inside the ingestion container**, not as
a UI-deployed Airflow pipeline: there's no schedule to keep, and the CLI gives the run's result
directly in the terminal (`make om-sync`). The artifacts and the generated workflow config
reach the container through `openmetadata/artifacts/`, **bind-mounted read-only** and written
by the host: the container only reads, so nothing there is ever owned by the container's user.
The config contains a short-lived admin JWT (login with the stack's upstream-default local
admin), so the directory is gitignored. `overrideLineage: true` makes re-running replace, not
accumulate, lineage.

**Elementary's own models are excluded** from the catalog (`package_name == 'elementary'` in
`sync`, plus a schema filter of `bronze|silver|gold` on the workflow): they're its monitoring
tables (~30), noise next to the 11 tables that hold project data. dbt tests (`run_results.json`)
are not ingested either — not asked for, and Elementary already reports them.

**Not in CI, on purpose.** The stack is ~4.6 GiB of containers at idle and takes several
minutes to become healthy; nothing under `.github/` references it, and the PR checks are
unchanged. It is optional local-exploration infrastructure.

**Resource gate (measured, not assumed)**, this machine, Piero's SeaweedFS also up, WSL2
`memory=11GB processors=6 swap=4GB` (`C:\Users\prios\.wslconfig`) → Docker sees 14.88 GiB and
6 CPUs; OpenMetadata's official minimum is 6 GiB and 4 vCPUs to Docker. Idle: ingestion
1.61 GiB, elasticsearch 1.54 GiB, server 1.05 GiB, postgres 259 MiB (~4.6 GiB together).
During this task's own ingestion workflow (sampled every 3 s with `docker stats`): the whole
stack peaked at 4.76 GiB and 457 % CPU (of 600 %), the `ingestion` container alone at
1.85 GiB / 446 %. Not measured at the previous 7.4 GiB WSL2 limit, so nothing here says
whether it fits there.

## What column-level lineage covers, and what it doesn't

Verified live, once, by hand (not pinned by a test: `check` asserts only `amount`), for every column of `gold.fact_transactions`, `dim_account`, `dim_date` and
`silver.transactions`: each traces back to a `bronze.*` column through every model in between,
including `amount` (`bronze.transactions.amount -> silver.transactions.amount ->
gold.fact_transactions.amount`), `flow_type` (`bronze.statements.account_kind` +
`bronze.transactions.amount`) and `is_internal_transfer` (seven bronze columns, through
`internal_transfer_matches`). What it does not cover:

- **`silver.transactions.occurrence_number` has no upstream column.** It is
  `row_number() over (partition by ...)`; OpenMetadata's parser records no column lineage for a
  window function's output, so the chain for that column (and `gold.fact_transactions`'
  copy of it) ends at silver. The table-level edge exists.
- Lineage is the parser's reading of the SQL, not an exact derivation: multi-column
  expressions list every input column (the `is_internal_transfer` case above), with no notion
  of which one mattered.
- It depends on `dbt docs generate` having run against a built lake (it needs live S3 and a
  built `dbt/pfp.duckdb`), and on the manifest/catalog being from the same build.
- An incremental model's compiled SQL references its own table (`{{ this }}`) once the table
  exists; OpenMetadata produced no self-edge for `silver.transactions`, but that is observed
  behavior of 2.0.2, not a guarantee.

## Alternatives considered

- **A custom Python connector (`CustomDatabase` + `sourcePythonClass`)** that yields the
  tables inside the ingestion framework. The "official" extension point, but it can only be
  exercised inside the container, and a small stdlib REST client with a unit-testable core does the
  same job. Worth revisiting if OpenMetadata later ships a DuckDB connector.
- **Reading the artifacts from SeaweedFS (`dbtConfigType: s3`)** instead of a bind mount:
  another moving part (credentials in the workflow config, artifacts uploaded first) for no
  gain, since the manifest needs rewriting on the host anyway.
- **Declaring bronze columns in `sources.yml`** so dbt's own artifacts carry them: touches the
  dbt project for a catalog concern and duplicates the pyarrow schema in a second place;
  `sync` reads the one that already writes bronze.
- **Rewriting the dbt models** to reference bronze through a view instead of `delta_scan()`:
  changes production SQL (ADR 0011) to suit a tool.
- **DataHub**: rejected in `tasks/plan-phase2.md` (heavier); not revisited.
- **Wiring the stack into CI**: rejected above.

## Consequences

- `make om-up`, `make om-sync`, `make om-down` exist; running them needs Docker with enough
  memory, a built lake and `.env` exported (SETUP.md section 10).
- Adding a new dbt source means adding its pyarrow schema to `bronze_tables()`, or `sync`
  exits 2 naming the source instead of registering a table with no columns.
- `bronze_tables()` imports `lakehouse.bronze`'s private `_TRANSACTIONS_SCHEMA` and
  `_STATEMENTS_SCHEMA`; if bronze gains a public schema registry, switch to it.
- Open: whether OpenMetadata should also ingest dbt tests, ownership and tags (Phase 3, with
  dashboards), and whether the resource footprint is acceptable at a smaller WSL2 limit.

## Related

- [OpenMetadata](../components/openmetadata.md) — the component this decision built.
- [dbt silver](../components/dbt-silver.md) and [dbt gold](../components/dbt-gold.md) — the
  models whose lineage it shows.
- [Elementary](../components/elementary.md) — excluded from the catalog; its dbt tests stay
  where they are.
- [CI](../components/ci.md) — deliberately doesn't run this.
- [ADR 0007](0007-ephemeral-per-pr-environments.md) — the ephemeral, project-named, `down -v`
  pattern the compose file follows.
- [ADR 0011](0011-delta-scan-as-a-dbt-source.md) — why bronze isn't a DuckDB table.

## Update 2026-09-19

The DuckDB workaround this ADR describes (no DuckDB connector in OpenMetadata, hence a script registering the tables) is retired by task T30 of the Phase 2 extension: once dbt stores silver and gold in PostgreSQL ([ADR 0029](0029-dbt-stores-silver-and-gold-in-postgres.md)), OpenMetadata reads them with its native connector. The column-level lineage from dbt's artifacts stays.
