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
| Processing | DuckDB (engine) + delta-rs | No JVM, no cluster; Spark (PySpark) comes in once volume or a demo gives a measurable reason. Since the Phase 2 extension DuckDB is only the engine: silver and gold are stored in PostgreSQL ([ADR 0029](brain/decisions/0029-dbt-stores-silver-and-gold-in-postgres.md)) |
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
- Repo structure, `docker-compose` (SeaweedFS as local S3; at the time silver lived in an embedded DuckDB file, no Postgres: PostgreSQL arrived in the Phase 2 extension), `.gitignore` + `gitleaks`.
- `Transaction` schema (pydantic) and BCP/Scotiabank parsers with `pdfplumber` + `pikepdf`; OCR with `pytesseract` for scanned pages.
- File hash (file-level dedup) + basic reconciliation.
- Bronze layer in Delta (delta-rs) on SeaweedFS.
- Initial dbt project (bronze → silver) with tests.
- GitHub Actions: `dbt build`, tests, `ruff`, `sqlfluff` on every PR.

**Closes:** modeling, basic quality, CI/CD, data security.

### Phase 2 — Orchestration + Governance *(closed 2026-09-18; extended 2026-09-19 and re-closed 2026-09-21: PostgreSQL store and Superset dashboards, T26–T37)*
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
- Still open: real-data validation of the Scotiabank parser, and (done on 2026-09-26, T19) the numeric CI rules leaving warn-mode.

**Extension (added 2026-09-19, T26–T33): PostgreSQL as dbt's store, then the dashboard.** The owner wants to look at the data in an open-source BI tool, and the catalog (OpenMetadata) and the pipeline (Dagster) related to it, while dbt builds. A DuckDB file has a single writer, so this phase was reopened on purpose ([ADR 0029](brain/decisions/0029-dbt-stores-silver-and-gold-in-postgres.md)):
- dbt keeps DuckDB as the engine (it reads bronze from the lake) and stores silver and gold in **PostgreSQL** (T26); the scripts, Dagster wiring and tests that opened the DuckDB file read Postgres (T27); Elementary keeps its own small DuckDB file (T28); CI's ephemeral environment and the PR data diff run on Postgres (T29).
- OpenMetadata reads Postgres with its native connector, retiring the DuckDB workaround (T30); Dagster shows where each model is stored (T31).
- **Apache Superset** (open source, zero cost, its own stack) over a read-only role on gold, with dashboards for cash flow, savings and each fund's monthly return (T32).
- Phase 3 (ML) starts after T33. Details: [`tasks/todo-phase2.md`](tasks/todo-phase2.md).

### Phase 3 — ML in production *(started 2026-09-27)*
**Goal:** deploy and monitor, not just train.
- Automatic transaction categorization (classification): the model proposes a category, the owner
  confirms or overrides -- never assigned silently ([ADR 0043](brain/decisions/0043-transaction-categorization-human-in-the-loop-labeling.md)).
  Label-collection infrastructure and a **trained classifier both built** (a cold-start guesser,
  the labeling file, `gold.dim_category`/`gold.rpt_movements.category`; TF-IDF character n-grams +
  logistic regression, MLflow-tracked, scored against the rules baseline --
  [ADR 0044](brain/decisions/0044-category-classifier-char-ngrams-vs-rules-baseline.md)) and
  scored on the owner's own labels (589 descriptions, 10 categories: macro-F1 0.49 on the 543
  reviewed ones, merchant-grouped 3-fold CV, against 0.23 for the rules; ADR 0044's 2026-10-04
  amendment). Batch categorization at ingest (ADR 0045) and Evidently drift monitoring (ADR 0046)
  are built; a live FastAPI endpoint is optional, only if a real caller ever needs one.
- Monthly spend forecasting (time series), per category: **specified 2026-10-04** together with the Phase 6 savings-goal projection ([spec](docs/specs/category-forecast-and-savings-goal.md), [ADR 0048](brain/decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md), tasks T56-T62): fixed expenses proposed and confirmed by the owner, simple models chosen by a rolling-origin backtest against a baseline, empirical intervals.
- Anomalous-charge detection.

**Closes:** MLOps. Identity, the public URL and the upload portal (T39-T50) are frozen once this
starts: built and documented, but no target audience for this portfolio values them, so no more
effort goes there unless something breaks (owner's call, 2026-09-27).

### Phase 4 — Cloud + IaC
**Goal:** the cloud "nice to have" that shows up in job postings.
- Terraform to provision infra on AWS or GCP (free tier).
- Stack deployment; secrets in a secrets manager (never hardcoded).

**Closes:** cloud, infrastructure as code.

### Phase 5 — Serving + Uploader
**Goal:** make the repo demonstrable and operable.
- The dashboard is **Apache Superset**, built in the Phase 2 extension (T32), not here: open source and zero cost, the owner will not use Power BI (2026-09-19).
- Minimal uploader (`st.file_uploader`) → saves to SeaweedFS → triggers the pipeline; a form to type the manual Excel's movements and balances could live here too.

**Closes:** end-to-end delivery, a showcase for recruiters.

**Status: already covered, built under other phases (checked 2026-10-07).** Against the plan
above:
- The dashboard line is exactly what T32-T37 (Phase 2 extension) built: Superset, dashboards as
  code, one Compose project.
- The uploader line is covered too, well past "minimal": the request-based upload portal
  (T39-T50, ADR 0040/0041) is Dex-authenticated, accepts up to 10 statement PDFs per request
  accepted or rejected as a whole, emails the owner a review alert and the sender at each step,
  and has its own Excel section for savings and investments (`docs/manual-data.md`) -- the
  "form to type the manual Excel's movements" above, covered by an upload instead of a typed
  form, same end result (no hand-typing a bank statement). It shipped grouped under Phase 3 in
  this file's own closing note (line below) and tagged `[Phase 5]` in
  [`tasks/backlog.md`](tasks/backlog.md), not under this section -- a labeling gap, not a scope
  gap. Nothing from this phase's plan is outstanding.
- The 2026-09-19 scope note below ("the uploader stays at its minimal, functional version") no
  longer describes what exists; it was true when written, before T46-T50 added the request
  workflow, review and Excel section on top of the original single-file upload.

### Phase 6 — Savings-goal projection *(planned, added 2026-09-19)*
**Goal:** answer "given my real cash flow, how long until I reach my savings goal?"
- Banco Ripley as a third source (the owner's savings account, in soles). It gives no statements, so its movements come from a **manual Excel** typed month by month, with the same reconciliation rules ([ADR 0027](brain/decisions/0027-manual-excel-for-ripley-savings-and-investment-tracking.md), [`docs/manual-data.md`](docs/manual-data.md)).
- **Investment tracking** (three Tyba funds and Flip), from a second sheet of the same Excel: contributions, withdrawals and month-end valuations, to see each fund's monthly return (Modified Dietz, `gold.fct_investment_monthly`, [ADR 0028](brain/decisions/0028-investment-return-is-modified-dietz-per-fund-and-month.md)). Tracked separately from the goal. **Built.**
- A projection over the gold tables: time to reach a target amount **in dollars** (soles converted at an owner-entered rate), after filling an emergency fund calculated from spending and income, at the observed monthly flow, leaving out transfers between the owner's own accounts. **Specified 2026-10-04** (with the Phase 3 spend forecast it depends on): the owner sets the goal, the answer is a range over three scenarios ([spec](docs/specs/category-forecast-and-savings-goal.md), [ADR 0048](brain/decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md)).
- A **sol/dólar exchange-rate projection** section so dollar accounts and dollar goals can be converted. It exists **only in this phase**: bronze, silver and gold keep never converting currencies; the projection converts on its own, on top of gold.
- **Scope decision (amended 2026-10-04):** Ripley savings are the emergency fund and investments are risk savings. The goal is shown on two lines, `liquid` only and `with_risk`, because mutual funds are long term and market-dependent; the owner picks which one his goal means ([ADR 0025](brain/decisions/0025-savings-goal-projection-counts-liquid-savings-only.md)).

**Closes:** turning the platform from "what happened" into "what happens next" on the owner's own data. Details and open questions: [`brain/phases/phase-6.md`](brain/phases/phase-6.md).

### Phase 7 — Alerting *(built, added 2026-09-19)*
**Goal:** be told when something breaks instead of having to look.
- Errors and warnings (dbt tests with `error`/`warn` severity, files that need review) delivered by **email or Microsoft Teams**: **errors the moment they appear, warnings in a weekly digest** ([ADR 0026](brain/decisions/0026-alerts-errors-now-warnings-weekly-names-and-counts-only.md)).
- Messages carry names and counts only, never data from a real statement ([ADR 0004](brain/decisions/0004-real-pdfs-never-leave-your-machine.md) applies to anything that leaves the process).
- Includes the small `scripts/poc.py` fix so `make poc` shows dbt's result lines on real output. Not wired: Dagster-triggered alerts (run `make alert` after a run).

**Closes:** operations and observability. Details and open questions: [`brain/phases/phase-7.md`](brain/phases/phase-7.md).

> **Order:** phases 6 and 7 were added after Phase 2 closed and do not renumber 3–5. The next steps in practice are listed in [`tasks/backlog.md`](tasks/backlog.md).

> **Scope note (2026-09-19):** the uploader stays at its minimal, functional version. None of the target job postings value frontend skills; the value is in what happens *after* the file comes in (parsing, reconciliation, MERGE, orchestration, ML). **Update 2026-10-07:** it grew past "minimal" anyway, driven by real needs (T46-T50: a request can hold several files, review before it lands, an alert email, an Excel section) rather than by frontend polish -- the spirit of this note held, only the word "minimal" didn't. See Phase 5's status note above.

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
