---
type: component
phase: 2
status: built
task: T21
---

# dagster

Wraps the existing `pfp ingest` + `dbt build` sequence as one Dagster DAG, rather than
reimplementing either — a `bronze` asset that calls `organizer.organize()` +
`bronze.write_statement()` directly, and every dbt node as its own Dagster asset via
`dagster-dbt`, with the real bronze -> silver dependency edge. `make poc` and the raw
`pfp`/`dbt` CLI commands are untouched: Dagster owns the DAG'd, CI-proven path, not the manual
one (ADR 0004's masked-dump debugging loop still needs no DAG in the way).

## Pieces

| Piece | What it does |
|---|---|
| [`orchestration/assets/bronze.py`](../../orchestration/assets/bronze.py) | The `bronze` asset: `organizer.organize()` + `bronze.write_statement()`, the same two calls `ingestion.cli._run_ingest()` makes for `pfp ingest` -- never a shelled-out `subprocess.run(["pfp", "ingest"])`. `BronzeIngestConfig` defaults `user_id`/`inbox_root`/`archive_root` from the same `PFP_USER`/`PFP_INBOX_ROOT`/`PFP_ARCHIVE_ROOT` env vars the CLI and CI already use |
| [`orchestration/assets/dbt_project.py`](../../orchestration/assets/dbt_project.py) | The whole dbt project as one Dagster multi-asset (`dagster_dbt.dbt_assets`), one Dagster asset key per dbt node -- today `transactions`, `internal_transfer_matches`, `internal_transfers`, `unmatched_transfers`; whatever a future model adds shows up automatically, no per-model wiring. `BronzeSourceDbtTranslator` collapses dbt's two `bronze` sources (`transactions`, `statements`) onto the one Python `bronze` asset that actually writes them, so the graph shows one real edge, not two invented stubs. `_dbt_build_args()` (T21, [ADR 0021](../decisions/0021-ci-invokes-the-dagster-pipeline.md)) forwards `DBT_SELECT`/`DBT_STATE_PATH` into the underlying `dbt build`, carrying ADR 0008's impact-based CI selection through unchanged |
| [`orchestration/definitions.py`](../../orchestration/definitions.py) | The top-level `Definitions` object: `bronze` + `dbt_models`, wired with `DbtCliResource(project_dir=dbt_project)`. Discovered by the `dagster` CLI via `pyproject.toml`'s `[tool.dagster] module_name` for `dagster dev` only -- see the env var note below for `dagster asset materialize`/`asset list` |
| `orchestration` package + `[tool.dagster]` (`pyproject.toml`) | `orchestration` is a fourth hatch build package and import-linter root, forbidden from `ingestion`/`lakehouse` importing back into it (same direction `ingestion.cli` already orchestrates both from). Named `orchestration`, not `dagster`: naming it `dagster` would shadow the real library on `sys.path` for anything that adds the repo root to it (`uv run pytest`, via `pythonpath = ["."]`) -- confirmed by reproducing the shadowing directly |
| [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)'s `ephemeral-integration` job | `dagster asset materialize --select '*'` replaces the old separate `pfp ingest`/`dbt build` steps (T21, [ADR 0021](../decisions/0021-ci-invokes-the-dagster-pipeline.md)) |
| [`scripts/count_bronze_statements.py`](../../scripts/count_bronze_statements.py) | Prints `bronze.statements`' real row count -- what CI's idempotency proof compares before/after a second materialization, since a multi-asset `dagster asset materialize` doesn't stream a step's own log text to stdout the way a single-asset selection does |

## `DAGSTER_MODULE_NAME`, not `pyproject.toml`, for `asset materialize`/`asset list`

`dagster asset materialize --select '*'`/`dagster asset list` need
`DAGSTER_MODULE_NAME=orchestration.definitions` set (`.env.example`, already in CI's own job
`env:`) -- **not** the same mechanism as `pyproject.toml`'s own `[tool.dagster] module_name`
block. That block only drives `dagster dev`'s own workspace auto-discovery (`WorkspaceOpts`,
`dagster/_cli/dev.py`); `asset materialize`/`asset list` resolve their target through a
different code path (`PythonPointerOpts`, `dagster/_cli/asset.py`) that needs an explicit
`-m`/`-f` flag or `DAGSTER_MODULE_NAME` (`dagster_shared/cli/__init__.py`'s own `envvar=`) --
confirmed by reading `dagster`'s own CLI source, not assumed from either command's `--help`
text, which doesn't mention `pyproject.toml` at all. `dagster dev` (the local web UI, not
required for CI or `make poc`) needs neither flag nor env var.

## `dbt build`'s duckdb path needed an absolute override

`dbt/profiles.yml`'s `path` defaults to the *relative* `dbt/pfp.duckdb`, resolved against the
dbt CLI subprocess's own working directory -- correct for every manual/CI invocation before
T21 (`uv run dbt build --project-dir dbt --profiles-dir dbt`, always run from the repo root),
but `dagster-dbt`'s `DbtCliResource.cli()` runs that subprocess from `project_dir` itself
(`dbt/`), which doubles the path to `dbt/dbt/pfp.duckdb` and crashes every materialization
outright (reproduced directly, not a hypothetical). `orchestration/assets/dbt_project.py` sets
an absolute `PFP_DUCKDB_PATH` via `os.environ.setdefault(...)` at import time -- `setdefault`
so a test's own `tmp_path`-scoped override, or an operator's own exported value, still wins.
Since ADR 0029 the same module gives `PFP_ELEMENTARY_DUCKDB_PATH` (Elementary's own file, the one
DuckDB file left in the default flow) an absolute default too; silver and gold are in Postgres, so
the run needs the `PFP_PG_*` variables.

## Known, pre-existing: `deltalake` exit 134 during shutdown

Any command that reads a bronze Delta table and then exits -- `dagster asset materialize`
included, not new to T21 -- can print `terminate called without an active exception` and exit
134 *after* printing its real output (`SETUP.md`'s known issues, predates T21). CI pipes every
such command to `tee`/another command rather than redirecting alone with `>`, the same
established workaround the pre-T21 `pfp ingest` steps already relied on; see
[ADR 0021](../decisions/0021-ci-invokes-the-dagster-pipeline.md) and [CI](ci.md).

## Importing `orchestration.assets.dbt_project` needs AWS/LAKEHOUSE_URI env vars, even with no live S3

Several test modules import `BronzeSourceDbtTranslator`/`_dbt_build_args`, which pulls in
`orchestration/assets/dbt_project.py`'s own import-time `dbt parse` (no manifest exists on a
fresh checkout). The parse subprocess never connects to S3, but rendering `dbt/profiles.yml`'s
`secrets:` block *and* `dbt/models/sources.yml`'s own `LAKEHOUSE_URI` reference (both
`env_var()` with no default) still needs `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/
`AWS_ENDPOINT_URL`/`LAKEHOUSE_URI` set to *something*, even in a plain `pytest` run with no
SeaweedFS. Confirmed as two separate real CI failures, one per missing var (`tests`, exit code
2 at collection) -- not reproducible in every local environment (this machine's own
already-cached duckdb extensions plausibly take a different path than a genuinely fresh one),
so this was found by watching the actual CI run fail, twice, not by local reproduction. CI's
`tests` and `benchmarks` jobs (the latter collects every test module too, via `pytest -m
benchmark`, before filtering by marker) both carry the same four dummy values
`ephemeral-integration` already uses.

## How to use it and how to verify it

Needs SeaweedFS up and `.env` exported, same as `dbt build` (`SETUP.md` section 9):

```bash
make poc-up
set -a && source .env && set +a
uv run dagster asset list                       # the asset graph
uv run dagster asset materialize --select '*'    # the whole pipeline, end to end
```

- [`tests/test_dagster_bronze.py`](../../tests/test_dagster_bronze.py): the `bronze` asset
  alone, disk-backed lake, no live S3 needed -- config defaults, a real synthetic PDF organized
  and written to bronze, and idempotency on a second materialization.
- [`tests/test_dagster_dbt_translator.py`](../../tests/test_dagster_dbt_translator.py):
  `BronzeSourceDbtTranslator` alone, plain dict fixtures, no live dbt project or manifest.
- [`tests/test_dagster_dbt_build_args.py`](../../tests/test_dagster_dbt_build_args.py):
  `_dbt_build_args()` alone, no live dbt project.
- [`tests/test_dagster_definitions.py`](../../tests/test_dagster_definitions.py): the static
  asset graph shape -- every dbt node registered, the real bronze -> silver dependency edge --
  without materializing anything.
- [`tests/test_dagster_pipeline_integration.py`](../../tests/test_dagster_pipeline_integration.py)
  (`integration`-marked, real SeaweedFS): the whole pipeline materialized through Dagster
  produces the identical bronze + silver row counts the equivalent `pfp ingest` + `dbt build`
  sequence does, and a second materialization adds nothing new.
- [`tests/test_count_bronze_statements.py`](../../tests/test_count_bronze_statements.py):
  disk-backed, no live S3 needed.

## Related

- [ADR 0021: CI invokes the Dagster pipeline](../decisions/0021-ci-invokes-the-dagster-pipeline.md) — the CI-wiring decisions and their alternatives.
- [CI](ci.md) — `ephemeral-integration`'s full step list.
- [dbt silver](dbt-silver.md) — the dbt project this wraps.
- [Lakehouse](lakehouse.md) — what the `bronze` asset writes to.
- [ADR 0008: Impact-based CI](../decisions/0008-impact-based-ci.md) — the `state:modified+` selection `_dbt_build_args()` carries through.
