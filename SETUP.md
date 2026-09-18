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
```

`dbt deps` only needs re-running when `dbt/packages.yml` changes; `dbt/dbt_packages/` (gitignored)
caches the install. `dagster asset materialize` (section 9) and a plain `pytest` collecting the
`test_dagster_*` modules both trigger it automatically the first time
`orchestration/assets/dbt_project.py` is imported (`dagster-dbt`'s own `DbtProject.prepare()`) —
the explicit command above is only needed for a bare `dbt build`/`dbt parse`/`sqlfluff` call like
the ones on this line, which never import that module.

`dbt build` writes `dbt/pfp.duckdb` (gitignored), so the built tables can be inspected
afterwards: `duckdb dbt/pfp.duckdb -c "select count(*) from silver.transactions"`. Set
`PFP_DUCKDB_PATH` to put that file somewhere else.

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
that build already wrote — same prerequisites as `dbt build`:

```bash
export PFP_DUCKDB_PATH="$PWD/dbt/pfp.duckdb"   # must be absolute for edr, see below
uv run edr report --project-dir dbt --profiles-dir dbt --config-dir dbt/.edr \
  --file-path dbt/elementary_report.html
```

`PFP_DUCKDB_PATH` has to be absolute here, unlike every `dbt build`/`dbt test` command above:
`edr` runs its own internal dbt project from inside its own installed package directory, not this
repo, so `profiles.yml`'s relative default (`dbt/pfp.duckdb`) would resolve against *that*
directory instead and fail to find the database `dbt build` just wrote (confirmed directly:
`edr report` fails with `Cannot open file ".../site-packages/elementary/.../dbt/pfp.duckdb"` with
no override, and finds the right file with one).

`--config-dir dbt/.edr` opts out of Elementary's own anonymous usage tracking (`dbt/.edr/config.yml`,
committed) — without it the generated report embeds a PostHog project key that would let it phone
home when opened in a browser (ADR 0004, ADR 0022). Drop `--open-browser false` if you want it to
open automatically; `dbt/*.html` is gitignored.

`edr` needs its own connection profile literally named `elementary` in `dbt/profiles.yml` (not the
project's own `personal_finance_platform` profile) — already there, pointed at the same DuckDB
file and S3 secrets so it reads what `dbt build` just wrote, not a second database.

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

## 10. Browsing the catalog and lineage in OpenMetadata (T24)

Optional. `openmetadata/docker-compose.yml` runs OpenMetadata 2.0.2 with PostgreSQL and
Elasticsearch under its own project name (`pfp-om`), ephemeral like the SeaweedFS one
(ADR 0007): `make om-down` removes every volume. Make sure WSL2 has the memory first
(requirements table above); after editing `.wslconfig`, run `wsl --shutdown` from PowerShell.
CI never runs this stack (ADR 0023).

```bash
make poc-up                          # local S3, as in section 6
set -a && source .env && set +a
uv run dbt deps --project-dir dbt --profiles-dir dbt
uv run dbt build --project-dir dbt --profiles-dir dbt   # or `dagster asset materialize`, section 9

make om-up                           # ~5 minutes to become healthy the first time
make om-sync                         # docs generate, register tables, ingest, check the lineage
```

`make om-sync` ends with `OK: 1 column-level path(s) from ...bronze.transactions.amount`, or
exits 1 if `gold.fact_transactions.amount` no longer traces back to bronze. Then open
<http://localhost:8585> (login `admin@open-metadata.org` / `admin`, the stack's upstream local
default) and browse *Explore* -> `pfp_duckdb` -> `gold` -> `fact_transactions` -> *Lineage*,
with *Column level lineage* on. The same from the API:

```bash
TOKEN=$(curl -s -X POST localhost:8585/api/v1/users/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"admin@open-metadata.org\",\"password\":\"$(printf admin | base64)\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["accessToken"])')
curl -s -H "Authorization: Bearer $TOKEN" \
  "localhost:8585/api/v1/lineage/getLineage?fqn=pfp_duckdb.pfp.gold.fact_transactions&type=table&upstreamDepth=10&downstreamDepth=0"
```

Re-run `make om-sync` after any `dbt build` that changes models; it is idempotent. `make om-down`
when done. Elementary's own models are not catalogued and dbt tests are not ingested.

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
| `metadata ingest` logs `Unable to find the node or columns in the catalog file for dbt node: source.personal_finance_platform.bronze.*` (and the `operation.*` on-run-end hooks) | Expected and harmless: dbt's catalog can't see bronze (`delta_scan()` isn't a DuckDB relation) and hooks have no columns. Bronze's tables and columns are registered by `scripts/openmetadata_sync.py` instead; the run still ends `Success %: 100.0` |
| `make om-sync`'s `check` prints `FAIL: no column-level path ...` and exits 1 | Column lineage stopped short of bronze. Reproduced on purpose by ingesting `dbt/target/manifest.json` as-is instead of the copy `sync` writes to `openmetadata/artifacts/manifest.json` (its `delta_scan(...)` paths aren't tables to OpenMetadata's SQL parser, ADR 0023): re-run `make om-sync`, which regenerates the copy |
| Upstream's own `docker-compose-postgres.yml` leaves `docker-volume/db-data-postgres` behind and `rm -rf` fails with `Permission denied` | Not applicable to `openmetadata/docker-compose.yml`: it uses named volumes, so `make om-down` (`down -v`) removes everything (checked: no `pfp-om_*` volume left) |
