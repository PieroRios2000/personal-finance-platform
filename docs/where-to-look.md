# Where to look at each stage of the platform

The pipeline is: **PDF inbox → bronze (Delta on S3) → silver and gold (dbt, in Postgres) → Superset**,
with a classifier (MLflow, Evidently) and an orchestrator (Dagster) around it. Each stage has a
place you can open to see what it is doing. This page lists them in pipeline order, with the exact
URL or command and a few things to click.

Everything below was checked on 2026-10-04 against the `pfp-poc` stack (real data) unless a line
says **Not verified**. "Verified" means the URL answered or the command ran here; nobody looked at the
pages in a graphical browser, so what you *see* is described from the tool's own behaviour.

## At a glance

| Stage | Tool | Open it | Port | Real web UI? |
|---|---|---|---|---|
| Inbox and archive | files + `pfp` CLI | `ls ~/finance-data/inbox/<user>` | none | no, CLI |
| Object storage | SeaweedFS S3 | `http://localhost:8333` (API only) | 8333 | no: the API answers `403` in a browser; browse with DuckDB |
| Bronze tables | Delta Lake on S3 | `s3://lakehouse/bronze/<table>` | 8333 | no: query it with DuckDB |
| Ad-hoc SQL on the lake | DuckDB | `CALL start_ui_server();` | 4213 | yes (DuckDB UI) |
| Models, tests, lineage | dbt docs | `uv run dbt docs serve --port 8081` | 8081 | yes |
| Silver and gold | Postgres | `docker exec … psql` | 5432 | no, SQL only (use Superset SQL Lab for a UI) |
| Orchestration, runs, asset graph | Dagster | `uv run dagster dev` | 3000 | yes |
| Dashboards and SQL Lab | Superset | `http://localhost:8088` | 8088 | yes |
| Login | Dex | `http://localhost:5556/dex/.well-known/openid-configuration` | 5556 | no page of its own, only the login screen |
| Upload portal | upload | `http://localhost:5560` | 5560 | yes |
| Sign-up | dex-register | `http://localhost:5559` | 5559 | yes |
| Classifier runs | MLflow | `uv run mlflow ui --port 5001` | 5001 | yes |
| Drift report | Evidently | `~/finance-data/reports/category-drift-<date>.html` | file | yes (static HTML) |
| Data quality report | Elementary | `dbt/elementary_report.html` | file | yes (static HTML), **not verified** |
| Catalog and column lineage | OpenMetadata (optional) | `http://localhost:8585` after `make up-catalog` | 8585 | yes, **not verified** |

`make status` prints the URLs of the running stack.

## Start everything

```bash
cd ~/projects/personal-finance-platform
make up          # Postgres, SeaweedFS, Superset, Dex, upload portal, sign-up
make status      # containers and the URLs above
```

- `pfp-poc` (the real data) is **local only** ([ADR 0042](../brain/decisions/0042-public-url-shows-only-demo-data.md)): no tunnel, no public
  URL, every address here is `localhost`. Only `pfp-prod` runs the tunnel; its public URLs show the
  demo user, not real data.
- The web tools that are not containers (Dagster, dbt docs, MLflow, DuckDB UI) are started by hand
  in a terminal, with the repo's `.venv` (`uv run …`), and stop with `Ctrl+C`.
- Open the URLs in your Windows browser. WSL2 forwards `localhost` to Windows. The containers publish
  on `127.0.0.1`, which works; if a page does not load, see the last section.

## 1. Inbox and archive (the entry point)

The only manual step in the platform: you drop statement PDFs in `~/finance-data/inbox/<user>/`.

```bash
ls ~/finance-data/inbox/<user>        # waiting to be ingested
ls ~/finance-data/raw/<user>          # archive: bank/year/month once organized
uv run pfp --help                     # parse, import-manual, organize, ingest, backfill
uv run pfp ingest                     # organize the inbox, then write new statements to bronze
make ingest                           # same thing, with .env loaded
```

What to look at: the archive layout (a PDF is identified by its SHA-256, so the same file is never processed twice) and the counts `pfp ingest` prints. No web UI. Never open the PDFs on screen shares;
they are real statements.

## 2. S3 (SeaweedFS) and the bronze Delta tables

SeaweedFS is the local S3. Only its S3 API is published (port 8333); its own master/filer pages are
**not** published by this project, and `aws` and `mc` are not installed. A browser pointed at
`http://localhost:8333` gets `403 Access Denied`: that is the API refusing an unsigned request, not a
broken service. Browse it with DuckDB instead (section 3).

What is in the `lakehouse` bucket: `bronze/<table>/` for these Delta tables, each with data files
(Parquet) and a `_delta_log/` folder (one JSON per commit: this is what makes it Delta, and where the
table history lives):

`category_labels`, `ingested_files`, `investment_entries`, `statements`, `transactions`

List them (credentials come from `.env`, never printed):

```bash
set -a && source .env && set +a
ENDPOINT_HOST=$(echo "$AWS_ENDPOINT_URL" | sed -E 's#^[a-z]+://##; s#/$##')
duckdb <<SQL
INSTALL httpfs; LOAD httpfs; INSTALL delta; LOAD delta;
CREATE SECRET lakehouse (TYPE s3, PROVIDER config, KEY_ID '$AWS_ACCESS_KEY_ID',
    SECRET '$AWS_SECRET_ACCESS_KEY', REGION '${AWS_REGION:-us-east-1}',
    ENDPOINT '$ENDPOINT_HOST', URL_STYLE 'path', USE_SSL false);
SELECT file FROM glob('s3://lakehouse/bronze/**') LIMIT 30;          -- the bucket's files
SELECT count(*) FROM delta_scan('s3://lakehouse/bronze/ingested_files');
SQL
```

Things to try: `glob('s3://lakehouse/bronze/transactions/_delta_log/*')` to see one commit per
ingest; `DESCRIBE SELECT * FROM delta_scan('s3://lakehouse/bronze/statements')` for the columns;
compare `ingested_files` (one row per PDF) with `statements` (one per statement).
The same snippet is in [SETUP.md](../SETUP.md) section 7 ("Browsing the lake in DBeaver").

## 3. DuckDB (and its browser UI)

DuckDB is the engine dbt uses to read bronze (`delta_scan`). It is also the easiest way to look at the lake.

For a browser UI, start the UI server from the **same interactive session** that created the secret
(a secret lives only in its session), then leave the terminal open:

```bash
duckdb                       # then paste the INSTALL / CREATE SECRET block from section 2
D CALL start_ui_server();    # prints: UI server started at http://localhost:4213/
```

Open `http://localhost:4213`. Verified: the server starts and answers `200` with the UI's HTML.
**Not verified:** the notebook itself, and the S3 secret inside it. DuckDB documents that the UI
fetches its front-end from `ui.duckdb.org`, so it needs internet the first time. Stop it with
`CALL stop_ui_server();`. `duckdb -ui` also works for a local file, but it tries to open a browser
from WSL, which usually fails; starting the server by hand is more reliable.

## 4. dbt: models, tests and lineage

dbt turns bronze into `silver` (8 models: `transactions`, `category_labels`, `category_predictions`,
`internal_transfers`, …) and `gold` (13: `fact_transactions`, `dim_*`, `rpt_movements`,
`rpt_balances`, …) in Postgres.

```bash
set -a && source .env && set +a
uv run dbt docs generate --project-dir dbt --profiles-dir dbt     # reads Postgres's catalog, read-only
uv run dbt docs serve    --project-dir dbt --profiles-dir dbt --port 8081 --no-browser
```

Open `http://localhost:8081`. Verified: it answers `200` after `docs generate` against `pfp-poc`.
Things to click: a gold model such as `rpt_movements` → *Depends On* (the silver models it reads) and its
*Columns* with tests; the **blue lineage button** (bottom right) draws the graph from the source
(`bronze`) to gold; *Tests* on a model's page shows the ones attached to it.
`dbt docs generate` writes `dbt/target/` (gitignored). `dbt build` runs models and tests together
(`make build`).

## 5. Postgres (silver and gold)

No web UI; use Superset's SQL Lab (section 7) or `psql` in the container (the password never
leaves the container):

```bash
docker exec -it pfp-poc-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Inside: `\dn` (schemas `silver`, `gold`), `\dt gold.*` (13 tables), `\d gold.rpt_movements` (columns),
`SELECT count(*) FROM gold.fact_transactions;`. A desktop client (DBeaver) is described in
[SETUP.md](../SETUP.md) section 7. Superset reads gold through a read-only account.

## 6. Dagster: the pipeline as a graph, runs and checks

Dagster wraps bronze and every dbt model as an **asset**: 52 assets, 125 dbt tests as asset checks.
There are **no** schedules, sensors or jobs: nothing runs by itself, you launch runs by hand.

```bash
set -a && source .env && set +a
uv run dagster dev           # from the repo root; web UI at http://localhost:3000
```

Open `http://localhost:3000`. Verified here: the server serves on `127.0.0.1:3000` and its API reports
the 52 assets. Things to click:

- **Assets** → *Asset graph*: `bronze` on the left, silver, then gold. Click a node to see its code
  location, upstream and downstream, and its checks.
- Click a dbt model → *Overview*: after a materialization, `dagster/table_name` and `dagster/row_count`
  (see [SETUP.md](../SETUP.md) section 9).
- The **Materialize** button on the asset graph runs the selected assets (all of them if none is selected); the run page shows each step's log live.
- **Runs** lists past runs; **Deployment** shows the code location and that there are no schedules.

**Run history caveat.** `dagster dev` keeps its history in `DAGSTER_HOME`. With it unset, Dagster uses a
temporary folder and the history is gone when you stop the server (Dagster's documented behaviour; not
tested here). To keep it: `export DAGSTER_HOME=~/finance-data/dagster` (create the folder first) before
`dagster dev` **and** before any `dagster asset materialize`, so both write to the same place.
It needs `dagster-webserver`, which this repo's `dev` group now includes (before this page, `dagster dev`
failed with "dagster-webserver must be installed").

## 7. Superset: dashboards and SQL Lab

`http://localhost:8088` → *Sign in with Dex* → your email and password. What is there:

- **Dashboards** → `PFP finance`: 25 charts in sections (cash flow, capital, balances, investments,
  categories, forecast and goal, reconciliation, upload). The **Forecast & goal** section reads
  the virtual dataset `goal_dynamic` (SQL in `bi/sql/goal_dynamic.sql`, built from the gold tables
  `rpt_goal_plan`, `rpt_goal_cashflow` and `rpt_goal_balances`) and the gold tables
  `rpt_category_forecast`, `rpt_category_variance` and `rpt_forecast_realized` (monthly step:
  `make forecast`, [monthly routine](monthly-routine.md)). To try another goal, exchange rate,
  emergency months or forecast horizon, type it in the dashboard's filter bar (*Goal (US$)*,
  *Exchange rate (PEN per US$)*, *Emergency months*, *Forecast horizon (months)*) and press
  *Apply filters*; empty means the `Meta` value.
- **Charts** (`/chart/list/`): each chart's query and SQL (*View query*). **Datasets** (`/tablemodelview/list/`):
  the gold tables each chart reads.
- **SQL Lab** (`/sqllab/`) → database `PFP gold (read-only)`: any `SELECT` on `gold.*`. You only see
  rows of the `user_id` your account is scoped to (row-level security, [ADR 0036](../brain/decisions/0036-row-level-security-by-ingesting-user.md));
  an unscoped account sees empty tables (`make dex-scope`).
- The dashboard and charts are **code** (`bi/build_dashboards.py` → `bi/assets/`), imported at
  `make bi-up`. Edit them in the UI to explore, but the file wins on the next import.

## 8. Dex, the upload portal and sign-up

- **Dex** (`http://localhost:5556/dex`): no page of its own. Verified: `/dex/healthz` answers `200` and
  `/dex/.well-known/openid-configuration` returns the OIDC discovery JSON. You only see its login screen
  when Superset or the portal send you there. Accounts are managed with `make dex-add-user` / `make dex-scope`.
- **Upload portal** (`http://localhost:5560`): redirects (`302`) to Dex to sign in; then upload statements.
  They wait for `make ingest-uploads`.
- **Sign-up** (`http://localhost:5559`): needs the invite code from `.env` (not printed here).

## 9. MLflow: classifier runs

The category classifier ([ADR 0044](../brain/decisions/0044-category-classifier-char-ngrams-vs-rules-baseline.md)) logs each training to a local SQLite store.

```bash
uv run mlflow ui --backend-store-uri sqlite:///$HOME/finance-data/mlflow.db --port 5001
```

Open `http://localhost:5001`. Verified on a **copy** of the store: the UI answers `200` and the
`Default` experiment holds runs named `category-classifier`. Things to click: a run → *Metrics*
(`trained_macro_f1`, `rules_macro_f1`, `examples`, `categories`, `trusted_examples`) to see the model beat the
rules; *Artifacts* → `model`; select two runs and *Compare*. The trained model itself is at
`~/finance-data/models/category_classifier.joblib`.

Note: the runs' *artifacts* are written under the repo's `mlruns/` (gitignored, ~14 MB), not under
`~/finance-data` as the training script's docstring says; open the store read-only if you are
worried about the UI touching it: copy `mlflow.db` somewhere and point `--backend-store-uri` at the copy.

## 10. Drift report (Evidently)

```bash
make monitor-category-drift       # read-only on Postgres; aggregates only on the terminal
ls ~/finance-data/reports/        # category-drift-<date>.html
explorer.exe "$(wslpath -w ~/finance-data/reports)"   # opens the folder in Windows; double-click the HTML
```

A static HTML report: per-column drift of the classifier's inputs and assigned categories,
older movements versus the last 90 days ([ADR 0046](../brain/decisions/0046-classifier-drift-monitoring-with-evidently.md)).

## 11. Data quality report (Elementary) and the catalog (OpenMetadata)

Both optional. **Not verified here.**

- Elementary renders a static HTML from what `dbt build` wrote: see [SETUP.md](../SETUP.md) section 6
  (`edr report`, written to `dbt/elementary_report.html`).
- OpenMetadata adds a catalog and column-level lineage (bronze → gold). It needs ~4.6 GiB of RAM:
  `make up-catalog`, then `http://localhost:8585`; steps in SETUP.md section 10. `make om-down` deletes
  its volumes, so never use it on the real project by habit.

## If a page does not load

- `make status` and `docker ps`: every container should be `healthy`. `make up` again is safe.
- **Port already in use** (3000, 5001, 8081, 4213, 8088): another process has it. `ss -ltn | grep :<port>`
  shows it; pick another port (`--port`), or stop the other one. `pfp-prod` uses 8288, 5756, 5759.
- **Windows cannot reach `localhost`** while WSL2 is up: `wsl --shutdown` from PowerShell, reopen the
  terminal, `make up`.
- **Superset shows empty charts**: the account is not scoped to your `user_id` (`make dex-scope`).
- **`http://localhost:8333` says 403**: expected, see section 2.
- **A DuckDB-over-S3 query fails**: `make up` first, and `source .env` in the same shell.
