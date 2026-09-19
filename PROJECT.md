# Personal Finance Data Platform (End-to-End)

Personal portfolio project to demonstrate **Data Lead / Data Engineer** skills: ingestion, modeling, orchestration, data quality and governance, ML in production, and infrastructure as code — built entirely with **open source** tools and runnable locally at zero cost.

> **Usage context:** this document is the project's master spec. It's meant to be developed with Claude Code, phase by phase. Each phase is independently publishable on GitHub and closes one concrete technical gap.

---

## Goal

Ingest bank statement PDFs (BCP and Scotiabank today, Banco Ripley planned), process and validate them, model them under a medallion architecture, orchestrate the flow, run ML models on top of it, and serve it through a dashboard — replicating in open source what corporate environments do with Azure Data Factory + ADLS + Synapse/Databricks.

**Equivalence the project demonstrates (for interviews):**

| Azure world (work) | Open source equivalent (this project) |
|---|---|
| Azure Data Factory (orchestration) | Dagster |
| ADLS Gen2 / Blob (storage) | SeaweedFS (S3-compatible) |
| Delta/Parquet in the lake | Delta Lake on SeaweedFS |
| Synapse / Databricks (processing) | DuckDB + delta-rs; Apache Spark (PySpark) once there's a measurable reason |
| Power BI | Streamlit + Power BI |

---

## Design principles

1. **Data never touches Git.** The repository holds only code. Raw PDFs and processed tables live in SeaweedFS (local S3). Anyone can clone the repo, spin up the stack, and run it with *their own* PDFs.
2. **Fully open source and reproducible.** A single `docker compose up` brings up the whole platform.
3. **Idempotency.** Uploading the same statement twice never duplicates data. Deduplication happens at two levels (file and transaction).
4. **Reconciliation.** Every parsed PDF is validated against the balance/total the statement itself declares.
5. **Zero cost in development.** Everything runs locally; the cloud (Phase 4) is optional and only deployed for demonstration.

---

## Tech stack

| Layer | Tool | Notes |
|---|---|---|
| Ingestion / PDF parsing | `pdfplumber`, `pikepdf`, `pytesseract` | `pikepdf` unlocks password-protected PDFs; `pytesseract` reads scanned pages (pdfplumber already renders pages to an image, so PyMuPDF isn't needed) |
| Schema validation | `pydantic` | `Transaction` schema shared across all banks |
| Storage / lakehouse | SeaweedFS + Delta Lake | Parquet + ACID transactions + MERGE + time-travel. SeaweedFS replaces MinIO, whose Community edition went unmaintained in 2025 |
| Processing | DuckDB (embedded) + delta-rs | Phase 1 with no JVM, no cluster, no Postgres; Spark (PySpark) comes in once volume or a demo gives a measurable reason |
| Transformation | dbt | Medallion bronze/silver/gold; `incremental` materialization with a `merge` strategy |
| Orchestration | Dagster | (Alternative: Airflow, if ATS recognition is a priority) |
| Data quality | dbt tests + Great Expectations / Elementary | Quality tests and expectations |
| Governance / lineage | OpenMetadata or DataHub | Catalog and lineage |
| ML / MLOps | scikit-learn, MLflow, FastAPI, Evidently | Tracking, serving and drift monitoring |
| Serving | Streamlit (+ Power BI) | Dashboard and PDF uploader |
| Infra | Docker Compose, Terraform | IaC; free-tier cloud (Phase 4) |
| CI/CD | GitHub Actions | `dbt build`, tests and linters (`sqlfluff`, `ruff`) on every PR; ephemeral per-PR environment and impact-based CI (expensive jobs run only when a change affects them) |
| Security | `.gitignore` + `gitleaks` (pre-commit) | Safety net so data/secrets never reach Git |

---

## Data architecture

```
PDF (bank statement)
   │
   ▼
[ Ingestion ]  bank detection → bank-specific parser → Transaction schema (pydantic)
   │           + reconciliation (sum of transactions == total declared in the PDF)
   │           + file hash (SHA-256) for file-level dedup
   ▼
[ Bronze ]  Delta Lake on SeaweedFS — raw parsed data, append-only
   │
   ▼
[ Silver ]  dbt incremental + MERGE by business key (transaction-level dedup)
   │           normalized description, types, currency, account
   ▼
[ Gold ]    dbt — star schema: fact_transactions + dims (date, category, account)
   │
   ├──► [ ML / MLOps ]  categorization, spend forecasting, anomaly detection
   │
   └──► [ Serving ]  Streamlit dashboard + Power BI
```

The whole flow is triggered and coordinated by **Dagster**; **CI/CD**, **IaC** and **governance** are the cross-cutting platform layer.

---

## Deduplication (a key project detail)

**File level** — avoids reprocessing the same PDF:
- SHA-256 of the file's content.
- Registry of already-ingested files; if the hash exists, it's skipped.

**Transaction level** — avoids duplicates across *different* PDFs with overlapping movements (e.g. January's statement vs. a "last 60 days" one):
- A deterministic **business key** is built: `date + amount + normalized_description + account`.
- The description is normalized (trim, uppercase, strip filler codes) so the key stays stable across statements.
- `MERGE` (upsert) is used in Delta / dbt incremental: insert if new, ignore if identical, update if changed.

> This is the operation Delta Lake makes native that a pile of loose parquet files can't do. It's senior data-engineering language.

---

## Reconciliation (ties into migration roles)

Every parser validates that the sum of the extracted transactions matches the balance/total the statement itself declares. If it doesn't match, the parser fails and reports the discrepancy. This is the personal counterpart to the *"reconciliation and validation methodologies"* that data-migration roles ask for.

---

## Phases

### Phase 1 — Foundation
**Goal:** show discipline and good practices from the very first commit.
- Repo structure, `docker-compose` (SeaweedFS as local S3; embedded DuckDB, no Postgres), `.gitignore` + `gitleaks`.
- `Transaction` schema (pydantic) and BCP/Scotiabank parsers with `pdfplumber` + `pikepdf`; OCR with `pytesseract` for scanned pages.
- File hash (file-level dedup) + basic reconciliation.
- Bronze layer in Delta (delta-rs) on SeaweedFS.
- Initial dbt project (bronze → silver) with tests.
- GitHub Actions: `dbt build`, tests, `ruff`, `sqlfluff` on every PR.

**Closes:** modeling, basic quality, CI/CD, data security.

### Phase 2 — Orchestration + Governance
**Goal:** the most important gap for data-leadership roles.
- Dagster orchestrating: ingestion → dbt → tests → refresh.
- Incremental MERGE by business key (transaction-level dedup) in silver.
- Gold model (star schema): `fact_transactions` + dimensions.
- Great Expectations / Elementary for quality.
- Catalog and lineage (OpenMetadata or DataHub).

**Closes:** orchestration, data governance, idempotent deduplication.

**Status: built and closed (2026-09-18)** — [`brain/phases/phase-2.md`](brain/phases/phase-2.md). Against the plan above:
- Dagster orchestrates *bronze → every dbt node* (ingest → dbt build, with the dbt tests inside the build). The plan's "→ refresh" step has nothing to refresh yet (no dashboard until Phase 5), so it isn't built.
- Silver's incremental `MERGE` is keyed on `date + amount + normalized description + account_id + occurrence_number`; the occurrence number is scoped to one source file, which resolves the business-key note's open question. It also gained a model-layer balance-reconciliation test the plan didn't list.
- Gold is a star schema (`fact_transactions` + `dim_date`/`dim_account`/`dim_bank`/`dim_user`). No `dim_category` (Phase 3) and no FX conversion in these layers, by decision (only the Phase 6 projection converts, on top of gold).
- Quality: **Elementary** was chosen over Great Expectations (the plan left it open); a single row-count anomaly test on silver, in warn-mode.
- Catalog: **OpenMetadata** was chosen over DataHub. It is optional and local (not in CI) and needs a ~4.8 GiB peak; OpenMetadata 2.0.2 has no DuckDB connector, so a small script registers the tables (ADR 0023).
- Still open: real-data validation of the Scotiabank parser, and the numeric CI rules leaving warn-mode on 2026-09-26.

### Phase 3 — ML in production
**Goal:** deploy and monitor, not just train.
- Automatic transaction categorization (classification).
- Monthly spend forecasting (time series).
- Anomalous-charge detection.
- MLflow (tracking), FastAPI (serving), Evidently (drift).

**Closes:** MLOps.

### Phase 4 — Cloud + IaC
**Goal:** the cloud "nice to have" that shows up in job postings.
- Terraform to provision infra on AWS or GCP (free tier).
- Stack deployment; secrets in a secrets manager (never hardcoded).

**Closes:** cloud, infrastructure as code.

### Phase 5 — Serving + Uploader
**Goal:** make the repo demonstrable and operable.
- Streamlit dashboard over the gold tables.
- Minimal uploader (`st.file_uploader`) → saves to SeaweedFS → triggers the pipeline.
- (Optional) Power BI connection.

**Closes:** end-to-end delivery, a showcase for recruiters.

### Phase 6 — Savings-goal projection *(planned, added 2026-09-19)*
**Goal:** answer "given my real cash flow, how long until I reach my savings goal?"
- Banco Ripley as a third source (the owner's savings account, in soles). It gives no statements, so its movements come from a **manual Excel** typed month by month, with the same reconciliation rules ([ADR 0027](brain/decisions/0027-manual-excel-for-ripley-savings-and-investment-tracking.md), [`docs/manual-data.md`](docs/manual-data.md)).
- **Investment tracking** (three Tyba funds and Flip), from a second sheet of the same Excel: contributions, withdrawals and month-end valuations, to see each fund's monthly return. Tracked separately from the goal.
- A projection over the gold tables: time to reach a target amount (in soles or dollars) at the observed monthly flow, leaving out transfers between the owner's own accounts.
- A **sol/dólar exchange-rate projection** section so dollar accounts and dollar goals can be converted. It exists **only in this phase**: bronze, silver and gold keep never converting currencies; the projection converts on its own, on top of gold.
- **Scope decision:** only liquid money in bank accounts counts. Investments held on other platforms (mutual funds) are long term and market-dependent, so they are deliberately not part of the goal or the flow ([ADR 0025](brain/decisions/0025-savings-goal-projection-counts-liquid-savings-only.md)).

**Closes:** turning the platform from "what happened" into "what happens next" on the owner's own data. Details and open questions: [`brain/phases/phase-6.md`](brain/phases/phase-6.md).

### Phase 7 — Alerting *(built, added 2026-09-19)*
**Goal:** be told when something breaks instead of having to look.
- Errors and warnings (dbt tests with `error`/`warn` severity, files that need review) delivered by **email or Microsoft Teams**: **errors the moment they appear, warnings in a weekly digest** ([ADR 0026](brain/decisions/0026-alerts-errors-now-warnings-weekly-names-and-counts-only.md)).
- Messages carry names and counts only, never data from a real statement ([ADR 0004](brain/decisions/0004-real-pdfs-never-leave-your-machine.md) applies to anything that leaves the process).
- Includes the small `scripts/poc.py` fix so `make poc` shows dbt's result lines on real output. Not wired: Dagster-triggered alerts (run `make alert` after a run).

**Closes:** operations and observability. Details and open questions: [`brain/phases/phase-7.md`](brain/phases/phase-7.md).

> **Order:** phases 6 and 7 were added after Phase 2 closed and do not renumber 3–5. The next steps in practice are listed in [`tasks/backlog.md`](tasks/backlog.md).

> **Scope note:** the uploader stays at its minimal, functional version. None of the target job postings value frontend skills; the value is in what happens *after* the file comes in (parsing, reconciliation, MERGE, orchestration, ML).

---

## Suggested repository structure

```
.
├── docker-compose.yml
├── .gitignore
├── .pre-commit-config.yaml        # gitleaks, ruff, sqlfluff
├── README.md
├── PROJECT.md                     # this document
├── pyproject.toml
├── ingestion/
│   ├── schema.py                  # Transaction (pydantic)
│   ├── dispatcher.py              # detects the bank → routes to its parser
│   ├── reconciliation.py
│   ├── dedup.py                   # file hash + business key
│   ├── ocr.py                     # pytesseract for scanned pages
│   └── parsers/
│       ├── base.py
│       ├── bcp.py
│       └── scotiabank.py
├── lakehouse/                     # Delta / S3 utilities
├── dbt/
│   ├── models/
│   │   ├── bronze/
│   │   ├── silver/
│   │   └── gold/
│   └── tests/
├── orchestration/                 # Dagster (assets, jobs, schedules)
├── ml/
│   ├── categorization/
│   ├── forecasting/
│   ├── anomaly/
│   └── serving/                   # FastAPI
├── app/                           # Streamlit (dashboard + uploader)
├── infra/                         # Terraform
└── .github/workflows/             # CI/CD
```

---

## How to showcase it (for the CV / interview)

- A public repo with a clear README, an architecture diagram, and GIFs/screenshots of the dashboard running.
- Interview line: *"At work I use ADF + ADLS + Synapse; in my project I replicated that architecture with Dagster + SeaweedFS (S3) + Delta + DuckDB, with idempotent incremental loads and business-key deduplication via MERGE in Delta."*
- Each phase is a milestone with its own PR and description, showing a clean commit history.
