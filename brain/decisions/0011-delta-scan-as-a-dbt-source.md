---
type: decision
phase: 1
status: accepted
date: 2026-09-13
---

# ADR 0011: `delta_scan()` as a dbt source, on an on-disk DuckDB

## Context

ADR 0002 settles that DuckDB reads what delta-rs writes, and ADR 0006 settles where bronze
lives (`LAKEHOUSE_URI`, `s3://lakehouse` against SeaweedFS locally). T16 has to connect the
two: dbt needs to declare `bronze.transactions` and `bronze.statements` as sources, but those
are Delta tables on S3-compatible storage, not tables in a database dbt can see. Three things
had to be decided before any modeling, and `tasks/plan.md`'s risk log flags the first of them
("DuckDB reading Delta on local S3: endpoint, path-style, SSL") as a medium risk to check at
the start of this task.

## Decision

- **A source is a `delta_scan()` call, declared through dbt-duckdb's `external_location`.**
  dbt-duckdb resolves a source to whatever `external_location` says, and the documentation is
  explicit that the value "does not need to be a path-like string; it can also be a function
  call"
  ([dbt-duckdb README](https://github.com/duckdb/dbt-duckdb#reading-from-external-files)). So
  `dbt/models/sources.yml` declares one f-string for the whole source —
  `delta_scan('{{ env_var('LAKEHOUSE_URI') }}/bronze/{name}')` — and `{name}` fills in per
  table. Nothing else is needed: no pre-hook creating a view, no staged model, no dbt-duckdb
  plugin.

- **DuckDB reaches SeaweedFS through its Secrets Manager, `PROVIDER config`.** The profile's
  `secrets:` block declares `TYPE s3` with `ENDPOINT` (host:port, no scheme), `URL_STYLE
  'path'`, `USE_SSL false` and the key/secret from the same environment variables
  `lakehouse/storage.py` reads, so dbt and the writer can never disagree about which lake they
  are pointed at. This is DuckDB's documented shape for a non-AWS, plain-HTTP endpoint
  ([S3 API support](https://duckdb.org/docs/stable/core_extensions/httpfs/s3api),
  [delta extension](https://duckdb.org/docs/stable/core_extensions/delta)), and the three
  endpoint options are not optional: without them DuckDB resolves `s3://lakehouse/...` against
  real AWS and fails with `Error performing GET https://s3.us-east-1.amazonaws.com/lakehouse/
  bronze/transactions/_delta_log/_last_checkpoint`. `URL_STYLE 'path'` is the same path-style
  addressing `storage_options()` asks delta-rs for with
  `aws_virtual_hosted_style_request=false` (ADR 0006).

- **dbt opens an on-disk DuckDB database, not `:memory:`** (`dbt/pfp.duckdb`, overridable with
  `PFP_DUCKDB_PATH`). The built silver tables then survive the run: they can be inspected
  (`duckdb dbt/pfp.duckdb`) after a failure, and T17b's base-vs-PR data diff is specified to
  compare "a DuckDB file per run", which an in-memory database cannot provide. `*.duckdb` is
  already gitignored (T1), so nothing about this reaches Git.

- **Silver casts nothing.** Bronze writes every table with one fixed pyarrow schema (ADR 0006)
  and those types survive `delta_scan()` unchanged — `date` is `DATE`, `amount` is
  `DECIMAL(18, 2)`, `ingested_at` is `TIMESTAMP WITH TIME ZONE`, confirmed with
  `describe select * from delta_scan(...)`. A cast in the model would only restate what the
  writer already guarantees. The one column silver does rework is `description`.

- **sqlfluff is configured from `pyproject.toml`, with the dbt templater.** sqlfluff refuses to
  take `templater` from a config file in a subdirectory of the working directory ("Templater
  cannot be set in a .sqlfluff file in a subdirectory of the current working directory"), so a
  `dbt/.sqlfluff` silently fell back to the jinja templater; `[tool.sqlfluff.*]` in
  `pyproject.toml` works and keeps every tool's configuration in the one file this repo
  already uses for ruff, mypy, pytest, coverage and import-linter.

## Alternatives considered

- **A `pre-hook` (or `on-run-start`) creating a view over `delta_scan()`, with the source
  declared against that view**: rejected. It is more moving parts for the same result, it puts
  the bronze location in SQL instead of in the source declaration where dbt's lineage and docs
  can see it, and dbt-duckdb's documented mechanism already covers the case.
- **dbt-duckdb's `delta` plugin**: rejected. Its own README marks it experimental, and it
  solves a problem this project does not have (it materializes Python-side reads); the core
  `delta` extension reads the same tables natively, in the database.
- **A staging model that reads the Delta table into a DuckDB table, with silver built on
  that**: rejected as a layer with no job. Bronze *is* the staging layer (medallion), and
  silver is one `select` away from it.
- **An in-memory DuckDB**: rejected for the reasons above — it would make a failed run
  un-inspectable and block T17b.
- **The plain jinja templater for sqlfluff** (sqlfluff stubs `source()` and `ref()` itself, and
  needs no environment variables to lint): rejected because it lints a placeholder rather than
  the `delta_scan(...)` expression DuckDB actually runs. Worth revisiting in T17 if requiring
  `.env` to lint SQL turns out to be awkward in CI.
- **Declaring `dbt-duckdb` a dev dependency**: rejected. `dbt build` is a step of the
  platform's own end-to-end flow in `tasks/plan.md`, not a check a developer runs; sqlfluff,
  which only lints, is the dev dependency.

## Consequences

- `dbt` and the Python writer share one source of truth for where the lake is and how to reach
  it (`.env`), so a change of endpoint or bucket needs no dbt-side edit.
- Every dbt command needs both `--project-dir dbt` and `--profiles-dir dbt`, because
  `profiles.yml` lives in the project directory and dbt only searches `--profiles-dir`,
  `DBT_PROFILES_DIR`, the working directory and `~/.dbt`.
- `dbt build` and `uv run sqlfluff lint dbt/models` both need the `.env` values exported and
  SeaweedFS running; neither works from a bare checkout. Documented in SETUP.md.
- The silver model re-applies `ingestion.schema.normalize_description()`'s rules in SQL, which
  couples two implementations of the same four rules. Deliberate (bronze is append-only and
  holds rows written by older parser versions, so silver is where the column contract is
  enforced), but it is a coupling to keep in step, and it is called out in both places.
- Nothing here ties the project to DuckDB's Delta support beyond one line of YAML: if
  `delta_scan()` ever became a problem, the same source could point at a different function
  without touching a model.

## Related

- [dbt silver](../components/dbt-silver.md) — the component this decision builds.
- [ADR 0002: DuckDB + delta-rs before Spark](0002-duckdb-and-delta-rs-before-spark.md) — the
  risk this task was told to check first.
- [ADR 0006: Lake location by URI](0006-lake-location-by-uri.md) — the environment variables
  and the fixed pyarrow schema this relies on.
- [ADR 0003: Local S3 with SeaweedFS](0003-local-s3-with-seaweedfs.md)
- [Medallion architecture](../concepts/medallion.md)
- [Reconciliation](../concepts/reconciliation.md) — the continuity level this project's silver
  tests add.
- [Phase 1](../phases/phase-1.md)
