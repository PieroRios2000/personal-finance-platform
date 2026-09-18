# Ingesting your own bank statement PDFs

A step-by-step walkthrough for running the platform against **real** statements (BCP and
Scotiabank) on your own machine. Everything stays local: real PDFs, the `.env` and the
account key never leave it ([ADR 0004](../brain/decisions/0004-real-pdfs-never-leave-your-machine.md)).

If you only want to see the pipeline work, use the synthetic quickstart in the
[README](../README.md#quickstart-synthetic-data) instead — no PDFs needed.

> **One rule while asking for help** (from a colleague or an AI assistant): share only the
> **counts and generic messages** `make poc` prints. Never paste a balance, an account
> number, a movement description, or anything read from a PDF. If a statement fails, the
> failure reason is enough to fix a parser; the statement itself is not needed.

All commands run in a Linux shell (WSL2 on Windows) from the repository root, with
[`SETUP.md`](../SETUP.md) sections 1–4 already done (uv, Docker, `uv sync --locked`).

---

## 1. Put the PDFs in your inbox

```bash
mkdir -p ~/finance-data/inbox/<user>     # <user> is any name you pick, e.g. "alice"
chmod 700 ~/finance-data
# copy every PDF here: BCP and Scotiabank together, under any file name
chmod 600 ~/finance-data/inbox/<user>/*.pdf
```

- The folder name must match `PFP_USER` in your `.env` (next step).
- File names don't matter: the bank, account and period are read from the PDF's content.
- Copying from the Windows file explorer can leave `*:Zone.Identifier` files next to the
  PDFs; delete them: `find ~/finance-data -name '*:Zone.Identifier' -delete`.
- Once processed, a PDF is **moved** (never deleted) into
  `~/finance-data/raw/<user>/<bank>/<account>/<period>.pdf`. Repeats go to `_duplicates/`,
  unreadable or unreconciled ones to `_needs_review/`.

## 2. Fill in `.env`

```bash
cp .env.example .env && chmod 600 .env    # only if you don't have one yet
```

| Variable | What to put |
|---|---|
| `PFP_USER` | The folder name from step 1 |
| `PFP_ACCOUNT_KEY` | A secret key: `openssl rand -hex 32`. **Back it up outside the repo** — losing it changes every `account_id`, and every statement has to be reprocessed |
| `BCP_PDF_PASSWORD` | The password of your BCP PDFs |
| `SCOTIABANK_PDF_PASSWORD` | The password of your Scotiabank PDFs |
| `LAKEHOUSE_URI` | `s3://lakehouse` |
| `AWS_ENDPOINT_URL` | `http://localhost:8333` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Any pair you choose (e.g. `dev-key` / `dev-secret`); the local S3 is created with them |

`.env` is gitignored. Don't commit it, and don't hand it to an assistant.

## 3. One-off check: `make poc`

```bash
make poc
```

It brings up a local S3 (SeaweedFS), installs the dbt packages, runs `pfp ingest` over your
inbox, runs `dbt build`, and **tears everything down at the end**, success or failure. It
prints only pass/fail and counts — by construction never an amount, account or description
(see `scripts/poc.py`).

> `make poc` uses the fixed Docker Compose project `pfp-poc`. If you already started one
> with `make poc-up`, it is shut down (with its volume, i.e. the lake) when `make poc`
> finishes. Your archived PDFs in `~/finance-data/raw/` and the tables dbt already built in
> `dbt/pfp.duckdb` are kept.

### Reading the output

- `Archived: N  Duplicates: N  Needs review: N`
  - **Archived** — read correctly and filed under `~/finance-data/raw/`.
  - **Duplicates** — same content as one already archived.
  - **Needs review** — could not be read or did not reconcile. **Aim for 0.**
- `Bronze: N statement(s) written, M already ingested`
- dbt's `PASS`/`FAIL` lines and `Done. PASS=.. WARN=.. ERROR=..`. A `WARN` from Elementary's
  anomaly test does not fail the build ([ADR 0022](../brain/decisions/0022-elementary-anomaly-detection-and-warn-mode.md)).
- `Internal transfers: N matched pair(s), M unmatched candidate(s)` — counts only.

## 4. If something fails or a movement isn't read

Collect only this:

- The full `make poc` output (it contains no amounts).
- For each `Needs review` item, the generic reason:
  - `wrong or missing password (checked BCP_PDF_PASSWORD)` → check the `.env` password.
  - `no bank recognized this file's content` → layout not recognized.
  - `the statement did not reconcile` → some movement wasn't read: the movements don't add
    up to the balance the statement itself declares.
  - `could not parse the statement` → unexpected layout.
- How many files sit in each folder, without opening them:

  ```bash
  ls ~/finance-data/raw/<user>/_needs_review | wc -l
  ls ~/finance-data/raw/<user>/_duplicates | wc -l
  ```

If a parser has to be adjusted, work from the **masked** layout dump — digits become `9`,
text becomes `X`, and the file's path and metadata are never printed:

```bash
uv run --env-file .env scripts/inspect_pdf_layout.py <path-to-pdf> --password-env BCP_PDF_PASSWORD
# Scotiabank: --password-env SCOTIABANK_PDF_PASSWORD
```

Review that output yourself before sharing it with anyone. Parser fixes are
regression-tested against synthetic fixtures, never against your real file.

## 5. Explore your data (persistent run, no teardown)

`make poc` deletes the lake when it finishes. To browse your data, run the same flow by hand
and leave it up:

```bash
make poc-up                                             # local S3, left running
set -a && source .env && set +a
uv run dbt deps --project-dir dbt --profiles-dir dbt    # once, or after packages.yml changes
uv run pfp ingest --user "$PFP_USER"                    # PDFs -> bronze
uv run dbt build --project-dir dbt --profiles-dir dbt   # silver + gold + tests + Elementary
```

(`uv run dagster asset materialize --select '*'` does ingest + build as one DAG; see
[SETUP.md section 9](../SETUP.md#9-running-the-pipeline-through-dagster-t21).)

Then query the star schema:

```bash
duckdb dbt/pfp.duckdb -c "select count(*) from gold.fact_transactions"
duckdb dbt/pfp.duckdb -c "select bank, flow_type, currency, count(*) from gold.fact_transactions group by all"
```

or open `dbt/pfp.duckdb` in DBeaver
([SETUP.md section 7](../SETUP.md#7-browsing-the-lake-in-dbeaver)): schemas `silver`, `gold`
and `elementary` are there.

The gold layer is `gold.fact_transactions` plus `gold.dim_date`, `gold.dim_account`,
`gold.dim_bank` and `gold.dim_user`. `flow_type` (`ingreso` / `egreso` / `pago`) is the
direction of a movement, consistent across banks despite their opposite sign conventions;
filter `is_internal_transfer = false` for real income/spending. Currencies (PEN / USD) are
never converted or mixed.

Optional: a local quality report (`PFP_DUCKDB_PATH` must be absolute for `edr`) and the
catalog with column-level lineage — see [SETUP.md](../SETUP.md) (Elementary subsection,
section 10) and [ADR 0023](../brain/decisions/0023-openmetadata-catalog-and-column-lineage-from-dbt-artifacts.md).

When finished: `make poc-down` (removes the lake; your PDFs in `~/finance-data/raw/` stay).

## 6. After fixing a parser: reprocess

Processed PDFs are never deleted, so a parser fix can reach them:

```bash
uv run pfp backfill --user "$PFP_USER" --dry-run   # what it would replace
uv run pfp backfill --user "$PFP_USER"             # replaces each file's rows in bronze
uv run dbt build --project-dir dbt --profiles-dir dbt
```

`backfill` replaces a file's rows rather than appending
([ADR 0010](../brain/decisions/0010-bronze-backfill-replaces-not-versions.md)) and only
touches archived statements. Files in `_needs_review/` are not reprocessed by it: move them
back into `~/finance-data/inbox/<user>/` and run `pfp ingest`. If the lake was already torn
down (`make poc`, `make poc-down`), redo section 5 from `pfp ingest`.

## Checklist

- [ ] PDFs in `~/finance-data/inbox/<user>/`, `chmod 600`
- [ ] `.env` complete; `PFP_USER` equals the folder name
- [ ] `PFP_ACCOUNT_KEY` backed up outside the repo
- [ ] `make poc` run, output kept
- [ ] `Needs review` is 0, or each reason is noted
- [ ] (Optional) persistent run from section 5 to browse the data
