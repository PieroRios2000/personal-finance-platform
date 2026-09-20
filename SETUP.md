# Setup

Steps to reproduce the project on another computer. Run them once, in order;
section 5 checks that everything came out right at the end.

## 1. Requirements

Versions the project was tested with. Newer versions usually work;
if something breaks, fall back to these.

| Program | Tested version | What for | Needed from |
|---|---|---|---|
| Windows + WSL2 with Ubuntu | Ubuntu 26.04 LTS, kernel 6.6 | Linux development environment | Start |
| Git | 2.53 | Version control | Start |
| curl | 8.18 | Download the uv installer | Start |
| uv | 0.12.13 | Installs Python and the libraries per `uv.lock` | Start |
| Python | 3.12.14 (installed by uv) | Project language | Start |
| pre-commit | 4.6.2 | Security guards and lint before every commit | Start |
| make | 4.4 | Check shortcuts (`make check-task`) | T4 |
| Docker Desktop | 4.43.2 (Engine 28.3.2, Compose 2.38) | Local S3 with SeaweedFS | T13 |
| OpenMetadata stack (optional, `openmetadata/docker-compose.yml`) | OpenMetadata 2.0.2 (server, ingestion, PostgreSQL) + Elasticsearch 9.3.0 | Catalog and column-level lineage over the dbt project (T24). **Needs ~4.6 GiB of RAM at idle (measured: ~4.8 GiB peak while ingesting) and up to ~4.5 of 6 vCPUs while ingesting**, on top of SeaweedFS; the official minimum is 6 GiB and 4 vCPUs given to Docker. ~12 GiB of images. Measured on WSL2 with `memory=11GB processors=6 swap=4GB` in `C:\Users\<you>\.wslconfig` (Docker then sees 14.88 GiB); not measured at 7.4 GiB. Never run by CI | T24 |
| Superset stack (optional, `bi/docker-compose.yml`) | Apache Superset 5.0.0 + `psycopg2-binary` 2.9.10 | Dashboards over the gold schema (T32). **Measured: 335 MiB of RAM idle and after loading every chart**; the image is 3.7 GB on disk. Never run by CI | T32 |
| Tesseract OCR + Spanish language pack | 5.5 | OCR for scanned PDFs | T11b |
| GitHub CLI (`gh`) | 2.46 | PRs from the terminal | Optional |

No need to install a system Python or Go: uv brings its own Python, and pre-commit
builds gitleaks on its own.

## 2. Windows: WSL2 and Docker Desktop

1. In an admin PowerShell: `wsl --install` (installs WSL2 with Ubuntu) and reboot.
2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and turn on
   **Settings → Resources → WSL integration** for your distro.
3. Inside Ubuntu, give yourself access to Docker without `sudo`:

   ```bash
   sudo usermod -aG docker "$USER"
   ```

   Then, in PowerShell, run `wsl --shutdown` and reopen Ubuntu so it picks up the group.

## 3. Ubuntu (WSL): system packages and uv

```bash
sudo apt update
sudo apt install -y git curl make tesseract-ocr tesseract-ocr-spa gh

# uv, at the tested version (installs into ~/.local/bin, no sudo needed)
curl -LsSf https://astral.sh/uv/0.12.13/install.sh | sh
```

Open a new terminal so `~/.local/bin` lands on your `PATH`.

## 4. Project

Clone inside the Linux filesystem (`~/…`), not under `/mnt/c`: it's much faster.

```bash
git clone https://github.com/PieroRios2000/personal-finance-platform.git
cd personal-finance-platform

uv sync --locked                    # Python 3.12 + every exact library from uv.lock
uv tool install pre-commit==4.6.2
pre-commit install                  # enables the hooks in this clone
pre-commit install-hooks            # downloads the hooks (gitleaks, ruff…) once

cp .env.example .env && chmod 600 .env   # fill in the values; .env never gets committed
```

Two of `.env`'s values matter before you ingest anything (T6, ADR 0005 and ADR 0009):

- **`PFP_ACCOUNT_KEY`**: the secret HMAC key `hash_account()` uses to turn a bank name and a
  real account number into `account_id`, so the number itself is never stored. Generate one
  with `openssl rand -hex 32` (or `python -c "import secrets; print(secrets.token_hex(32))"`)
  and paste it into `.env`. **Back it up outside the repo** (a password manager, for example):
  losing it changes every `account_id` on the next run, which means re-processing every
  statement from the original PDFs — this is a known risk, tracked in `tasks/plan.md`.
- **`PFP_USER`**: the default `--user` for `pfp ingest`/`pfp parse` (ADR 0009) when it isn't
  passed on the command line; convenient for a single-person install. `--user` always wins
  over it.

Real PDFs live **outside the repo**, readable only by your user (the full walkthrough, from
folder to first `make poc`, is [docs/ingesting-your-own-pdfs.md](docs/ingesting-your-own-pdfs.md)):

```bash
mkdir -p ~/finance-data/inbox/<user>    # per-user inbox, e.g. inbox/piero
chmod 700 ~/finance-data
# drop that user's PDFs there, from any bank, under any name, then:
chmod 600 ~/finance-data/inbox/*/*.pdf
```

Once processed (`pfp ingest`, from T12b and T14), each PDF gets filed into
`~/finance-data/raw/<user>/<bank>/<account>/<period>.pdf`; repeats go to `_duplicates/` and
unrecognized ones go to `_needs_review/`. A file is never deleted.

### Python libraries

They're consolidated in one place and all installed with `uv sync --locked`:

- `pyproject.toml`: the direct dependencies.
- `uv.lock`: the exact version (with a hash) of every library, including transitive ones.
  This is what guarantees every machine installs the exact same thing.

| Library | Pinned version | Type | What for |
|---|---|---|---|
| pydantic | 2.13.5 | runtime | Transaction models and validation |
| pikepdf | 10.13.0.post1 | runtime | Open and decrypt password-protected PDFs |
| pdfplumber | 0.11.10 | runtime | Read PDF text along with positions |
| pytesseract | 0.3.13 | runtime | OCR (Spanish) for scanned pages with no text layer |
| deltalake | 1.6.3 | runtime | Write and read bronze's Delta tables (T14, ADR 0006) |
| pyarrow | 25.0.1 | runtime | Explicit table schemas for Delta writes (T14, ADR 0006) |
| psycopg | 3.3.6 | dev | Talks to PostgreSQL from the integration tests (create a throwaway database, count rows, check the read-only role) (T26) |
| types-PyYAML | 6.0.12 | dev | Type stubs for PyYAML (mypy strict) |
| dbt-duckdb | 1.11.0 (dbt-core 1.12.4) | runtime | Builds silver from bronze (T16, ADR 0011). Runtime, not dev: `dbt build` is a step of the platform's own flow, not a check |
| duckdb | 1.5.5 | runtime | The engine dbt runs on; reads Delta off S3 with `delta_scan()` (T16, ADR 0002) |
| dagster | 1.13.23 | runtime | Orchestrates bronze + dbt as one DAG (T21). Runtime: `dagster asset materialize` is a way to run the platform's own flow, same as `pfp ingest` + `dbt build` by hand |
| dagster-dbt | 0.29.23 | runtime | Wraps the dbt project as Dagster assets, one per dbt node (T21) |
| elementary-data | 0.26.0 | dev | The `edr` CLI (`edr report`/`edr monitor`), for rendering a local observability report from what `dbt build` already wrote (T22, ADR 0022). Elementary itself is a **dbt package**, not a `uv` dependency — see `dbt/packages.yml` and the "Elementary" subsection under section 6 below |
| sqlfluff | 4.3.0 | dev | Lints the dbt project's SQL (T16) |
| sqlfluff-templater-dbt | 4.3.0 | dev | Lets sqlfluff compile the dbt project, so it lints the real `delta_scan(...)` SQL |
| fpdf2 | 2.8.8 | dev | Generate synthetic PDFs inside the tests |
| pytest | 9.1.1 | dev | Tests |
| pytest-cov | 7.1.0 | dev | Coverage |
| pytest-benchmark | 5.3.0 | dev | Parsing and bronze-write benchmarks, base vs PR (T15) |
| openpyxl | 3.1.5 | runtime | Writes (and later reads) the manual Excel for Ripley savings and investments (`scripts/make_manual_templates.py`) |
| types-openpyxl | 3.1.5 | dev | Type stubs for openpyxl (mypy strict) |
| pytest-xdist | 3.8.0 | dev | Runs the integration suite on several workers in CI (`-n 4`), each with its own test lake |
| ruff | 0.16.7 | dev | Lint and format |
| mypy | 2.3.1 | dev | Types (strict mode) |
| diff-cover | 10.5.1 | dev | Coverage of changed lines against the base branch |
| import-linter | 2.15 | dev | Architecture contracts (who can import whom) |
| pip-audit | 2.10.1 | dev | Known vulnerabilities in dependencies |
| bandit | 1.9.4 | dev | Security issues in the code |

Don't use `pip install` or a `requirements.txt`: they drift out of sync with the lock. To add a
library: `uv add <lib>` (or `uv add --dev <lib>`), then commit `pyproject.toml` and `uv.lock`
together, updating this table.

## 5. Verification

```bash
make check-task                     # lint, format, types, tests, floor-guard and architecture
pre-commit run --all-files
docker run --rm hello-world         # Docker Desktop must be running
tesseract --list-langs              # should include "spa"
```

All green = the environment is ready.

## 6. Building silver with dbt (T16)

> **Phase 2 extension (T26–T33):** silver and gold live in **PostgreSQL**, not in `dbt/pfp.duckdb`
> ([ADR 0029](brain/decisions/0029-dbt-stores-silver-and-gold-in-postgres.md)). Since T27 that is the
> **default**: `make poc-up` starts the local S3 *and* Postgres, and every `dbt build` below writes
> there. Section 10 (OpenMetadata) is on Postgres since T30; section 7 (DBeaver) still describes the
> DuckDB-file version.

### PostgreSQL as dbt's store (T26, default since T27)

```bash
# 1. In .env, fill the PFP_PG_* variables (template: .env.example). Generate the two secrets,
#    e.g. `openssl rand -hex 16`, with no quotes or backslashes in them.
make poc-up                                             # local S3 + PostgreSQL 16 on 127.0.0.1:${PFP_PG_PORT}
set -a && source .env && set +a
uv run dbt build --project-dir dbt --profiles-dir dbt   # default target: postgres
```

`PFP_DBT_TARGET=local` selects the old DuckDB file instead (`dbt/pfp.duckdb`); CI's base-versus-PR
data diff still uses it until T29. `make pg-up` starts only Postgres (the local S3 stays as it is).

DuckDB stays the engine (it reads bronze off S3); silver and gold are created in the Postgres
database `PFP_PG_DATABASE`, schemas `silver` and `gold`. **Elementary keeps its own small DuckDB file**
(`dbt/elementary.duckdb`, gitignored) because its views and its results upload do not work through
the attach. The first time the Postgres volume is created it also makes the read-only role `pfp_bi`
(password `PFP_PG_BI_PASSWORD`; its sessions are read-only), which can connect and `select` from
`gold` and nothing else, including tables dbt recreates later (`postgres/grants.sql`): that is the
login BI tools use. It can still see table and column *names* in Postgres's catalog, not their data.
The role exists only in a volume created by this version: with an older volume, or after changing
`PFP_PG_BI_PASSWORD`, run `make poc-down` (removes the volume, lake included) and `make pg-up` again.
`make pg-down` only stops Postgres.

The `edr` CLI reads Elementary's own file (`PFP_ELEMENTARY_DUCKDB_PATH`, section "Elementary" below).

`make check-task` doesn't cover this: dbt reads bronze's Delta tables straight off local S3, so
it needs SeaweedFS running and `.env` exported into the shell. `profiles.yml` lives inside the
project directory, and dbt only searches `--profiles-dir`, `DBT_PROFILES_DIR`, the working
directory and `~/.dbt` — so both flags are needed, from the repository root:

```bash
make poc-up                          # local S3 (leave it running)
set -a && source .env && set +a      # LAKEHOUSE_URI + the AWS_* values dbt reads

uv run dbt deps --project-dir dbt --profiles-dir dbt    # once, or after packages.yml changes (T22)
uv run dbt build --project-dir dbt --profiles-dir dbt   # silver + gold + Elementary's own models/tests
uv run sqlfluff lint dbt/models                         # SQL style
uv run pytest -m integration                            # the S3-backed tests, deselected by default
uv run pytest -m integration -n 4                       # same, on 4 workers (what CI does; ~2.5x faster on 6 CPUs)
```

`dbt deps` only needs re-running when `dbt/packages.yml` changes; `dbt/dbt_packages/` (gitignored)
caches the install. `dagster asset materialize` (section 9) and a plain `pytest` collecting the
`test_dagster_*` modules both trigger it automatically the first time
`orchestration/assets/dbt_project.py` is imported (`dagster-dbt`'s own `DbtProject.prepare()`) —
the explicit command above is only needed for a bare `dbt build`/`dbt parse`/`sqlfluff` call like
the ones on this line, which never import that module.

`dbt build` writes silver and gold to Postgres, so the built tables can be inspected afterwards
with any Postgres client, e.g. `PGPASSWORD=... psql -h 127.0.0.1 -p $PFP_PG_PORT -U pfp -d pfp -c
"select count(*) from silver.transactions"`. The integration tests each use their own throwaway
database (`pfp_test_<worker>`), so they never touch `pfp`; a few empty ones may remain in the volume.
With `PFP_DBT_TARGET=local` the tables are in `dbt/pfp.duckdb` (`PFP_DUCKDB_PATH` moves that file).

`sqlfluff` uses the **dbt** templater, so it compiles the project and needs the same
environment variables `dbt build` does; without them it fails to connect rather than linting a
placeholder. Its configuration is `[tool.sqlfluff.*]` in `pyproject.toml` (sqlfluff refuses to
take `templater` from a config file in a subdirectory of the working directory).

Two things to expect: the continuity test fails on a lake whose statement history has holes —
that is the point, it names the periods you never archived (see
[reconciliation](brain/concepts/reconciliation.md)) — and `dbt build` reads whatever
`LAKEHOUSE_URI` points at, so pointing it at a prefix (`LAKEHOUSE_URI=s3://lakehouse/scratch`)
is how you try things out without touching your real bronze.

### Elementary: anomaly detection and a local quality report (T22)

`dbt build` above already builds Elementary's own models and runs its row-count anomaly test on
`silver.transactions` (`elementary_volume_anomalies_silver_transactions`,
`dbt/models/silver/schema.yml`) — no separate step. It's `severity: warn` (ADR 0022): a real
anomaly shows up as `WARN` in `dbt build`'s own output, but doesn't fail the build yet.

`edr report` (from the `elementary-data` package above) renders a local HTML report from what
that build already wrote. Elementary's tables live in **their own DuckDB file**
(`dbt/elementary.duckdb`, gitignored; silver and gold are in Postgres, ADR 0029), so `edr` needs
only that file, not the lake or Postgres:

```bash
export PFP_ELEMENTARY_DUCKDB_PATH="$PWD/dbt/elementary.duckdb"   # must be absolute for edr, see below
uv run edr report --project-dir dbt --profiles-dir dbt --config-dir dbt/.edr \
  --file-path dbt/elementary_report.html
```

The path has to be absolute here, unlike every `dbt build`/`dbt test` command above: `edr` runs its
own internal dbt project from inside its own installed package directory, not this repo, so a
relative path would resolve against *that* directory and `edr report` would fail to find the file
`dbt build` just wrote. (The default for `dbt build` and Dagster is `dbt/elementary.duckdb`; Dagster
sets an absolute one itself.) `make poc-down` deletes the file together with the database it
described.

`--config-dir dbt/.edr` opts out of Elementary's own anonymous usage tracking (`dbt/.edr/config.yml`,
committed) — without it the generated report embeds a PostHog project key that would let it phone
home when opened in a browser (ADR 0004, ADR 0022). Drop `--open-browser false` if you want it to
open automatically; `dbt/*.html` is gitignored.

`edr` needs its own connection profile literally named `elementary` in `dbt/profiles.yml` (not the
project's own `personal_finance_platform` profile) — already there, pointing at Elementary's DuckDB
file (attached under the alias `elem`, the catalog name dbt's views were created with, so the file
can have any name).

### `make poc`: the whole flow against your real PDFs (T17)

`make poc` runs the same flow as CI's `ephemeral-integration` job (ADR 0007) — `poc-up`,
`dbt deps`, `pfp ingest`, `dbt build` — but once, locally, against your own real inbox instead of the
synthetic fixture, and tears the environment down when it's done, success or failure. Unlike
every command above, its own output is deliberately narrow: only pass/fail and reconciliation
*counts* ever get printed (ADR 0004 — never a real balance, account number or description);
see `scripts/poc.py`'s docstring for exactly which lines that is and why.

```bash
make poc   # brings its own environment up and down; no need for poc-up first
```

## 7. Browsing the lake in DBeaver

`dbt/pfp.duckdb` (section 6) is a real on-disk DuckDB database, so any DuckDB-aware SQL client
can open it directly — DBeaver has a built-in driver for it. The commands below also use the
standalone `duckdb` CLI (not the same as the `duckdb` Python package `uv sync` already
installs): `curl https://install.duckdb.org | sh` if `which duckdb` comes back empty.

**Silver only, zero extra setup**, after at least one `dbt build`:

1. DBeaver → *Database* → *New Database Connection* → search **DuckDB** → Next.
2. *Path*: browse to this repo's `dbt/pfp.duckdb`.
3. *Test Connection* → DBeaver offers to download the DuckDB JDBC driver from Maven → Download.
4. Finish. `silver.transactions` shows up in the Database Navigator.

**Bronze too** (the raw Delta tables on SeaweedFS S3) needs a one-time setup, since dbt only
*reads* bronze through `delta_scan()` at build time — it never materializes it into
`pfp.duckdb`. Run this once, from the repository root, with SeaweedFS up and `.env` exported
(same prerequisites as section 6):

```bash
make poc-up
set -a && source .env && set +a
ENDPOINT_HOST=$(echo "$AWS_ENDPOINT_URL" | sed -E 's#^[a-z]+://##; s#/$##')

duckdb dbt/pfp.duckdb <<SQL
INSTALL httpfs; LOAD httpfs;

CREATE PERSISTENT SECRET lakehouse (
    TYPE s3,
    PROVIDER config,
    KEY_ID '$AWS_ACCESS_KEY_ID',
    SECRET '$AWS_SECRET_ACCESS_KEY',
    REGION '${AWS_REGION:-us-east-1}',
    ENDPOINT '$ENDPOINT_HOST',
    URL_STYLE 'path',
    USE_SSL false
);

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE OR REPLACE VIEW bronze.transactions   AS SELECT * FROM delta_scan('s3://lakehouse/bronze/transactions');
CREATE OR REPLACE VIEW bronze.statements     AS SELECT * FROM delta_scan('s3://lakehouse/bronze/statements');
CREATE OR REPLACE VIEW bronze.ingested_files AS SELECT * FROM delta_scan('s3://lakehouse/bronze/ingested_files');
SQL
```

`CREATE PERSISTENT SECRET` writes to `~/.duckdb/stored_secrets` (unencrypted — this is local
SeaweedFS, not real AWS credentials) and loads automatically into **every** DuckDB
connection on this machine from then on, DBeaver included; the views live inside
`pfp.duckdb` itself, so they show up in the Database Navigator next to `silver.*` with no
further per-connection setup. Re-run only the `duckdb dbt/pfp.duckdb -c "CREATE OR REPLACE
VIEW ..."` block if the bucket or table names ever change — the secret only needs creating
once. Querying `bronze.*` still needs `make poc-up` running, same as `dbt build` does.

## 8. Browsing the brain in Obsidian

`brain/README.md` already says this works; this section is the exact steps. `brain/` is
plain Markdown with relative links between notes (`[ADR 0009](../decisions/...)`), which
Obsidian's graph and backlinks views resolve natively — not only `[[wikilinks]]` — so opening
it as a vault needs no rework of the notes themselves.

1. Install [Obsidian](https://obsidian.md/) on Windows.
2. *Open folder as vault* → since this repo lives inside WSL2, point it at the Windows UNC
   path, not a Linux path Windows can't see directly:

   ```
   \\wsl.localhost\<distro>\home\<user>\projects\personal-finance-platform\brain
   ```

   (`<distro>` and `<user>` are yours — `wslpath -w <path>` from inside WSL prints the exact
   UNC path for any file or folder if you're unsure.)
3. Open the graph view (the icon in the left ribbon, or `Ctrl+G`): every ADR, component and
   concept note shows up connected. The three files under `brain/_templates/` appear isolated
   on purpose — they're blank starting points to copy, not notes with content to link.

`.obsidian/` (Obsidian's own per-machine view state — panes, graph layout, theme) is already
gitignored; it's never something to commit.

## 9. Running the pipeline through Dagster (T21)

`orchestration/definitions.py` wires the bronze asset and the whole dbt project (one Dagster
asset per dbt node, via `dagster-dbt`) into one DAG — the same prerequisites as section 6
(SeaweedFS up, `.env` exported):

```bash
make poc-up
set -a && source .env && set +a

uv run dagster asset list                       # the asset graph, bronze -> silver et al.
uv run dagster asset materialize --select '*'    # the whole pipeline, end to end
```

Both commands need `DAGSTER_MODULE_NAME=orchestration.definitions` in `.env` (already in
`.env.example`). This is *not* the same mechanism as `pyproject.toml`'s own `[tool.dagster]
module_name` block: that block only drives `dagster dev`'s own workspace auto-discovery
(`WorkspaceOpts`); `dagster asset list`/`dagster asset materialize` resolve their target
through a different code path (`PythonPointerOpts`) that needs an explicit `-m`/`-f` flag or
this env var — confirmed by reading `dagster`'s own CLI source
(`dagster/_cli/asset.py`, `dagster_shared/cli/__init__.py`), not assumed from either flag's
`--help` text, which doesn't mention `pyproject.toml` at all.

`dagster dev` (the local web UI, not required for CI or `make poc`) does use the
`pyproject.toml` block, so it needs no extra flag or env var: `uv run dagster dev`.

**What to look at (T31).** Open the *Assets* graph: `bronze` (the lake, Delta on S3) feeds the dbt
models (silver, then gold). After a materialization, click a dbt model and its latest
materialization shows `dagster/table_name` (`silver.transactions`, `gold.fact_transactions`: the
schema and table in Postgres) and `dagster/row_count` (measured in Postgres right after the build).
That is the lake, dbt and the database in one view. With `PFP_DBT_TARGET=local` (the DuckDB file)
only the table name is shown, since there is no Postgres to count in.

## 10. Browsing the catalog and lineage in OpenMetadata (T24)

Optional. `openmetadata/docker-compose.yml` runs OpenMetadata 2.0.2 with PostgreSQL and
Elasticsearch under its own project name (`pfp-om`), ephemeral like the SeaweedFS one
(ADR 0007): `make om-down` removes every volume. Make sure WSL2 has the memory first
(requirements table above); after editing `.wslconfig`, run `wsl --shutdown` from PowerShell.
CI never runs this stack (ADR 0023).

```bash
make poc-up                          # local S3 and Postgres, as in section 6
set -a && source .env && set +a
uv run dbt deps --project-dir dbt --profiles-dir dbt
uv run dbt build --project-dir dbt --profiles-dir dbt   # or `dagster asset materialize`, section 9

make om-up                           # ~5 minutes to become healthy the first time
make om-sync                         # docs generate, register bronze, ingest silver/gold, check the lineage
```

Since T30 OpenMetadata reads silver and gold with its **native Postgres connector**: the `ingestion`
container joins the Docker network of your Postgres (`pfp-poc_default`; `make om-up` stops with a clear
message if `make poc-up` has not run, and `PFP_NETWORK` -- exported in your shell, not set in `.env` -- selects another project's network, whose Postgres service must be named `postgres`) and connects
as `postgres:5432` with the `PFP_PG_USER`/`PFP_PG_PASSWORD` from `.env`. Those credentials are written to
`openmetadata/artifacts/postgres-workflow.yaml` (gitignored, removed by `make om-down`), next to the
short-lived token the dbt workflow already needs. Run `make om-down` before `make poc-down`: while the
`ingestion` container is attached, Docker cannot remove the `pfp-poc_default` network. Only bronze -- Delta tables the connector cannot see --
is still registered by `scripts/openmetadata_sync.py`, from `lakehouse/bronze.py`'s schemas.

`make om-sync` ends with `OK: 1 column-level path(s) from ...bronze.transactions.amount`, or
exits 1 if `gold.fact_transactions.amount` no longer traces back to bronze. Then open
<http://localhost:8585> (login `admin@open-metadata.org` / `admin`, the stack's upstream local
default) and browse *Explore* -> `pfp_postgres` -> `pfp` -> `gold` -> `fact_transactions` -> *Lineage*,
with *Column level lineage* on. The same from the API:

```bash
TOKEN=$(curl -s -X POST localhost:8585/api/v1/users/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"admin@open-metadata.org\",\"password\":\"$(printf admin | base64)\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["accessToken"])')
curl -s -H "Authorization: Bearer $TOKEN" \
  "localhost:8585/api/v1/lineage/getLineage?fqn=pfp_postgres.pfp.gold.fact_transactions&type=table&upstreamDepth=10&downstreamDepth=0"
```

Re-run `make om-sync` after any `dbt build` that changes models; it is idempotent. `make om-down`
when done. Elementary's own models (a separate DuckDB file, not in Postgres) are not
catalogued and dbt tests are not ingested.

## 12. Dashboards in Apache Superset (T32)

Optional, like OpenMetadata: `bi/docker-compose.yml` runs Superset 5.0.0 under its own project
(`pfp-bi`). CI never runs it and `make poc-up` does not start it. **Measured: 335 MiB idle and after
loading every chart** (one container; the image is 3.7 GB on disk), far below OpenMetadata's ~4.6 GiB,
so no `.wslconfig` change is needed on top of section 10's.

```bash
make poc-up                          # local S3 and Postgres, as in section 6
# fill in .env (see .env.example): PFP_BI_DB_PASSWORD, PFP_BI_ADMIN_PASSWORD, PFP_BI_SECRET_KEY
set -a && source .env && set +a
uv run pfp ingest --user "$PFP_USER"                    # your data, as in section 6
uv run dbt build --project-dir dbt --profiles-dir dbt   # gold tables the charts read
make bi-up                           # builds the image the first time (~2 minutes)
```

Open <http://localhost:8088> (another port: `PFP_BI_PORT` in `.env`), user `admin`, password
`PFP_BI_ADMIN_PASSWORD`, then *Dashboards* -> **PFP finance**. From the top:

- **Summary cards** (HTML made with Superset's Handlebars chart): money in, money out, net and the
  number of movements for the filtered period, and your net position (assets minus debt) in the
  latest month with its change against the previous month.
- **Cash flow** (money in green, out red) and **balance per month** per account. Both use the
  *effect on you* (`signed_amount`, ADR 0031): a credit card charge is out, a payment is in, debt is
  a negative balance, and transfers between your own accounts count on both sides (a fee between
  banks shows in the net; filter *Internal transfer* to leave them out).
- **Investments**: a styled table with each fund's return, and `closing_basis` as a badge right
  beside it (`valuation` = a real month-end value, `last_movement` = only the balance at the last
  movement), plus the return per fund over time and a note on how to read it.
- **Movements** and **Statement balances**: every gold movement (`amount` as the bank prints it, and
  `signed_amount`, the effect on you: on a credit card a charge is negative and a payment positive,
  ADR 0031) (real descriptions: they never
  leave your machine, so don't screenshot them into a chat) and each account's declared closing
  balance per month, to check against the PDFs. Filter to one bank, account, currency and month and
  compare.

The filter bar (left side; open it with the arrow on its edge) applies to **every** chart:
**Currency** (one at a time, PEN first: currencies are never added), **Date range**, **Time grain**
(month by default; day, week, year on demand), **Year**, **Quarter**, **Month**, **Bank**,
**Account** (last four digits), **Flow type**, **Internal transfer** and **Fund**. The calendar
filters work on all charts because every dataset is a `gold.rpt_*` table carrying the same
`calendar_*` columns from the shared calendar (`gold.dim_date`, continuous from the first to the
last month of your data). The "latest balance" card shows `-` if the filters leave out the latest
month of the data.

The KPI cards need Superset to allow a `<style>` block, CSS classes and script evaluation for the
Handlebars template (`bi/superset_config.py`: `HTML_SANITIZATION_SCHEMA_EXTENSIONS` and
`TALISMAN_CONFIG`). Only people who can edit charts can write such HTML; keep that to admins.

**After pulling this change:** `uv run dbt build --project-dir dbt --profiles-dir dbt` (new `rpt_*`
tables and a continuous `dim_date`), then `make bi-down && make bi-up`.

- **`relation "gold.fct_account_balance_monthly" does not exist`** (or another gold table): the dashboard
  needs models added after your last `dbt build`. Pull `develop`, run `uv run dbt build --project-dir dbt
  --profiles-dir dbt`, and reload.
- **A chart with no data:** its table is empty. Count it (counts only, no values):
  `psql`/DBeaver `select count(*) from gold.fct_investment_monthly` -- the investments charts need the
  manual Excel loaded (`pfp import-manual`, then `dbt build`).

- Superset reads Postgres as the read-only role `pfp_bi`: it sees `gold` and nothing else, so it
  cannot read `silver` or change data.
- Its own users and dashboards live in a `superset` database of the same Postgres (created by
  `bi/init-metadata.sh`). `make bi-down` stops it; `make bi-reset` also forgets that state, and the next
  `make bi-up` re-imports the committed dashboards from `bi/assets/`.
- Run `make bi-down` (and `make om-down`) before `make poc-down`: while they are attached, Docker cannot
  remove the Postgres network.
- **Changing a dashboard:** edit `bi/build_dashboards.py`, then `rm -r bi/assets/*`, `make bi-reset bi-up`,
  `make bi-export`, and commit the new `bi/assets/`.
- If `pfp_bi` cannot log in: its password is only read when the Postgres volume is first created
  (`postgres/init-roles.sh`); if you changed `PFP_PG_BI_PASSWORD` since, either recreate the volume or
  `alter role pfp_bi password '...'`.

## 11. Alerts by email or Microsoft Teams (Phase 7)

Errors are sent **the moment they appear**; warnings are **queued and sent once a week** as one
digest, to read on the weekend. Only names and counts are ever sent (a failing test's name, how
many rows, how many files need review), never an amount, an account or a file name
([ADR 0026](brain/decisions/0026-alerts-errors-now-warnings-weekly-names-and-counts-only.md)).

1. Fill in the `ALERT_*` variables in `.env` (template in `.env.example`); a channel is on when
   its variables are set, and both can be on. **Wrap each value in single quotes**: `.env` is
   sourced by the shell, and a Teams URL contains `&` (which would cut it short), an app password
   may contain spaces:
   - **Email:** `ALERT_SMTP_HOST`, `ALERT_SMTP_PORT` (587, STARTTLS), `ALERT_SMTP_USER`,
     `ALERT_SMTP_PASSWORD`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` (comma-separated). Most providers
     need an *app password* here, not the account password. The server's certificate is verified;
     port 465 (SMTPS, implicit TLS) is not supported, only STARTTLS (usually 587).
   - **Teams:** `ALERT_TEAMS_WEBHOOK_URL`: in Teams, create a Workflows flow triggered by "When a
     Teams webhook request is received" that posts to your channel or chat, and paste its URL
     (whether your tenant allows it depends on its admin).
2. Errors: `make poc` sends them by itself after the build when a channel is configured. After a
   plain `dbt build` or Dagster run, run `make alert` (it reads `dbt/target/run_results.json`).
   The same command queues the warnings in `~/finance-data/alerts/warnings.jsonl` (private,
   outside the repo; change it with `ALERT_QUEUE_PATH`).
3. Weekly digest: `make alert-digest` sends everything queued and empties the queue (only if the
   send worked; otherwise the warnings stay for the next try). To run it every Saturday morning,
   add a cron line inside WSL (`crontab -e`; `sudo service cron start` if cron is not running):

   ```
   0 9 * * 6 cd ~/projects/personal-finance-platform && make alert-digest >> ~/finance-data/alerts/digest.log 2>&1
   ```

   Cron has a minimal `PATH`: put `PATH=/home/<you>/.local/bin:/usr/bin:/bin` (where `uv` lives) as
   the first line of the crontab, and create the log's folder first (`mkdir -p ~/finance-data/alerts`).
   The cron service must be started again after each WSL restart. Or use a Windows Task Scheduler task running
   `wsl -e bash -lc "cd ~/projects/personal-finance-platform && make alert-digest"` on Saturdays.
   The machine has to be on at that time. If a digest cannot be delivered to any channel the queue
   is kept (claimed as `warnings.jsonl.sending`) and goes out, with anything queued since, in the
   next digest; if at least one channel delivered it, the queue is emptied and the failing channel
   is reported (exit code 1).

   Exit codes: `make alert` returns 0 when the alerts were delivered (or there was nothing to send)
   and 1 when a channel failed, whether or not the build was healthy. An *error* alert whose
   delivery fails is not retried: the failure is printed and the exit code is 1, so look at
   `dbt/target/run_results.json` or re-run `make alert`.

## Reproducing CI locally (`make ci-local`)

A PR can fail in CI for a reason that never shows on your machine: a variable CI does not set, a
file that only exists in your working copy (`dbt/target`, `dbt/dbt_packages`, `.env`). `make ci-local`
removes that surprise by running CI's own jobs the way CI runs them:

```bash
git commit ...                 # CI only sees what is committed; uncommitted changes are refused
make ci-local                  # lint-types, tests, architecture, floor-guard (~3 min)
make ci-local-full             # + ephemeral-integration (~20 min; Docker; ports 8333 and 5432 free)
uv run python -m scripts.ci_local tests   # one job by name; --keep leaves the clean clone to inspect
```

The steps and the environment are read from `.github/workflows/ci.yml` itself (one definition, not a
copy), and they run in a **clean clone of your last commit** with `env -i`-style isolation: only `HOME`,
`PATH` and that job's own variables. So `tests`, which has no Postgres variables, runs without them,
exactly as in CI. Skipped with a printed reason: steps with an `if:` condition other than `always()`
and steps that need `sudo` (install Tesseract yourself if `tests` needs it). `ephemeral-integration`
binds ports 8333 and 5432, so it refuses to start while your `make poc-up` stack is running
(`make poc-down` first: that also removes the lake and Postgres volumes). Not covered: the
`security` job (gitleaks and pip-audit run as their own actions), `benchmarks` and `pr-data-diff`.

## Reviewing CI

Every PR runs `.github/workflows/ci.yml`: `lint-types`, `tests`, `security`, `architecture`
and `floor-guard`, plus `changes` and — only when `changes` says the PR affects them —
`benchmarks` (T15) and `ephemeral-integration` (T17, ADR 0007 and ADR 0008). From the
terminal:

```bash
gh pr checks <n>                     # pass/fail per job for PR <n>
gh run view <run_id>                 # which job and step failed, and the error
gh run view <run_id> --log-failed    # the full log of just the failed steps
gh run rerun <run_id> --failed       # re-run only what failed
```

`<run_id>` shows up in `gh run list` or in the PR's checks. A failure
in `lint-types` is also annotated on the exact file and line inside the PR's *Files changed*
tab (ruff via `--output-format=github`, mypy via a problem matcher). Until 2026-09-26,
`diff-cover`, `pip-audit`, `bandit`, `import-linter` and the benchmark comparison only warn
(see CONSTRAINTS.md); a red `X` on `tests`, `security`'s gitleaks step, `lint-types` or
`floor-guard` is what actually blocks the merge.

The benchmarks are deselected from the normal test run (a timing only means something against
a baseline from the same machine). To run them locally, and to reproduce CI's comparison:

```bash
uv run pytest -m benchmark                         # just the numbers
git checkout origin/develop -- ingestion lakehouse # measure the base branch
uv run pytest -m benchmark -q --benchmark-min-rounds=10 --benchmark-save=base
git checkout HEAD -- ingestion lakehouse           # back to your code
uv run pytest -m benchmark -q --benchmark-min-rounds=10 \
  --benchmark-compare --benchmark-compare-fail=mean:20%
```

## Known issues

| Symptom | Fix |
|---|---|
| `The command 'docker' could not be found in this WSL 2 distro` | Docker Desktop is closed or WSL integration is off (step 2) |
| Docker Desktop: `wsl-bootstrap … exit status 1` on startup | In PowerShell, `wsl --shutdown`, then reopen Docker Desktop; if it persists, `wsl --update` |
| `permission denied` on `/var/run/docker.sock` | Missing the `docker` group, or WSL wasn't restarted (section 2, step 3) |
| `gh pr edit` fails with a *Projects classic* error (gh 2.46) | Use `gh api --method PATCH repos/<owner>/<repo>/pulls/<n>`, or upgrade gh from cli.github.com |
| Files named `<PdfName>.pdf:Zone.Identifier` appear under `~/finance-data/` | Windows adds them when copying from File Explorer; delete them (`find ~/finance-data -name '*:Zone.Identifier' -delete`) — they're not part of the PDF |
| `terminate called without an active exception` after a `pfp ingest`/`pfp backfill` run that read bronze, with exit code 134 | The command already did its work and printed its report: this is `deltalake==1.6.3` aborting while the process shuts down, after `main()` returned. Reproducible on this machine with `deltalake` alone (three lines: open a `DeltaTable`, `to_pyarrow_table()`, exit), so it isn't the CLI's doing; `pytest` isn't affected. Noted while building T14c; needs its own fix (a `deltalake` upgrade is the first thing to try) — don't script around a `pfp` exit code until then |
| `dbt build`/`dbt test` exits non-zero with `Catalog Error: Table with name test_..._elementary_volume_anomalies...__metrics__tmp_... does not exist!`, right after printing `Done. PASS=... WARN=... ERROR=0` | Elementary's own `on-run-end` cleanup of its per-invocation temp tables (`elementary.clean_elementary_temp_tables()`) reproducibly crashes on this stack (dbt-duckdb 1.11.0, elementary 0.26.0) — always *after* every real result is already computed, so it never hides a failure, only dbt's own exit code afterward. `dbt/dbt_project.yml`'s `vars: clean_elementary_temp_tables: false` (T22) already works around it; if you see this anyway, check that var hasn't been reverted |
| `make om-up` takes ~5 minutes the first time (measured: 4m40s with the images already pulled) | Normal: `up --wait` blocks until every container, including `ingestion` (Airflow, the slowest), reports healthy. Give it the time before assuming a failure |
| `metadata ingest` logs `Unable to find the node or columns in the catalog file for dbt node: source.personal_finance_platform.bronze.*` (and the `operation.*` on-run-end hooks) | Expected and harmless: dbt's catalog can't see bronze (`delta_scan()` isn't a database relation) and hooks have no columns. Bronze's tables and columns are registered by `scripts/openmetadata_sync.py` instead; the run still ends `Success %: 100.0` |
| `make om-sync`'s `check` prints `FAIL: no column-level path ...` and exits 1 | Column lineage stopped short of bronze. Reproduced on purpose by ingesting `dbt/target/manifest.json` as-is instead of the copy `sync` writes to `openmetadata/artifacts/manifest.json` (its `delta_scan(...)` paths aren't tables to OpenMetadata's SQL parser, ADR 0023): re-run `make om-sync`, which regenerates the copy |
| Upstream's own `docker-compose-postgres.yml` leaves `docker-volume/db-data-postgres` behind and `rm -rf` fails with `Permission denied` | Not applicable to `openmetadata/docker-compose.yml`: it uses named volumes, so `make om-down` (`down -v`) removes everything (checked: no `pfp-om_*` volume left) |
