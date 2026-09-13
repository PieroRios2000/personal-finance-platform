# Implementation plan — Phase 1: Foundation

> Master spec: [`PROJECT.md`](../PROJECT.md). Detailed tasks: [`tasks/todo.md`](todo.md).
> Status: **approved** (PR #6); later changes come in via PR.

## Summary

Phase 1 leaves a platform that can run end-to-end locally:
a bank statement PDF (BCP or Scotiabank) gets parsed into the `Transaction` schema,
reconciled against the totals the PDF itself declares, skipped if already
ingested (SHA-256 hash), and written to the **bronze** layer (Delta Lake on local S3).
dbt transforms bronze → **silver** with tests. CI validates quality, security,
performance and architecture on every PR, and the **brain** (`brain/`) documents
the context and how each piece relates. Data is **per user and per account**, and
reconciliation is integral: every statement, continuity across periods, and
transfers between accounts.

**Verifiable result once the phase closes:**

```bash
docker compose up -d                  # local S3
cp /mnt/c/Users/<you>/Downloads/EECC*.pdf ~/finance-data/inbox/piero/   # any name works
uv run pfp ingest --user piero        # → filed into raw/piero/<bank>/<account>/, written to bronze
cp /mnt/c/Users/<you>/Downloads/EECC*.pdf ~/finance-data/inbox/piero/   # the same files again
uv run pfp ingest --user piero        # → "duplicate", 0 new rows
uv run dbt build --project-dir dbt    # → silver + tests green
```

## Changes from PROJECT.md

| PROJECT.md | This plan | Why |
|---|---|---|
| BCP, BBVA, Interbank banks | **BCP and Scotiabank** | Piero's decision (2026-09-12) |
| MinIO | **SeaweedFS** (approved 2026-09-12) | MinIO Community stopped publishing images (Oct 2025), went into maintenance (Dec 2025) and its repo is archived (2026): no more security patches |
| Postgres / DuckDB | Only embedded **DuckDB** | One less service; DuckDB covers Phase 1 |
| PySpark / DuckDB / Polars | **DuckDB + delta-rs** in Phase 1; Spark once there's a measurable reason | 7 GB of RAM in WSL; avoid three engines doing the same job |
| PyMuPDF, pytesseract | **pytesseract** for scanned pages (T11b); no PyMuPDF | There are scanned PDFs; pdfplumber already renders pages to an image for OCR |

`PROJECT.md` gets updated with these changes in task T3b.

## Architecture decisions

Every decision gets recorded as an ADR in `brain/decisions/` in the task where it's made.

| ADR | Decision | Why |
|---|---|---|
| 0001 | Python **3.12** managed with **uv** (`pyproject.toml` + `uv.lock`) | The system's 3.14 is too new for part of the stack (dbt has only recently supported it, with dependency caveats; Phase 2-3 tools tend to lag behind). uv installs Python without sudo and pins versions with a lockfile |
| 0002 | **DuckDB + delta-rs** (`deltalake`) before Spark | Same Delta format, no JVM or cluster; Spark comes in once volume or a demo justify it |
| 0003 | Local S3 with **SeaweedFS** instead of MinIO | Maintained, Apache 2.0, standard S3 API: switching servers means switching an endpoint |
| 0004 | **Real PDFs never leave your machine** | CI uses synthetic PDFs generated in the tests; parsers are designed from a masked layout dump |
| 0005 | `Transaction` with `user_id` and an account identified by `account_id` = HMAC-SHA256 of the bank and the full number (key `PFP_ACCOUNT_KEY` in `.env`) + the last 4 digits; the full number and the file name are never stored | No floating-point errors; several accounts per bank and per user without storing the number (a hash without a key is reversible by trying every possible number) |
| 0006 | Lake location by URI (`LAKEHOUSE_URI`) | `s3://…` locally/in integration CI, a disk path in unit tests |
| 0007 | **Ephemeral per-PR environments**: the same `docker-compose.yml` locally and in CI, with a unique project name, synthetic data, and always torn down at the end | Test every improvement against the real platform with no fixed servers or cost, and see its effect on the data (base vs PR), not just whether tests pass |
| 0008 | **Impact-based CI**: cheap checks (lint, types, unit tests, security) always run in full; expensive ones (ephemeral environment, dbt, benchmarks) only if the change affects them, per a dependency map; everything runs in full on `develop` and once a week | Evaluate what changes and what depends on it, not the whole project, without missing indirect effects: cheap checks take seconds and are what catches breakage between modules (mypy), and the full run catches whatever the map misses |
| 0009 | **Several users and several accounts in one install**: bank, account and period are read from the PDF's content, never from the file name; `user_id` on all data; PDFs land in a per-user inbox and get filed into `raw/<user>/<bank>/<account>/`; the lake is partitioned by `user_id` | More than one person and several accounts per bank; deleting someone's data means dropping their partition; the file name can contain account numbers |

## Structure once Phase 1 closes

```
.
├── .github/
│   ├── workflows/{branch-policy,ci}.yml
│   └── pull_request_template.md
├── brain/                    # brain: concepts, components, decisions, phases
├── dbt/                      # dbt project (bronze → silver)
├── ingestion/
│   ├── schema.py  dedup.py  reconciliation.py  dispatcher.py  cli.py
│   └── parsers/{base,bcp,scotiabank}.py
├── lakehouse/                # Delta writer + ingested-files registry
├── scripts/                  # inspect_pdf_layout.py, floor_guard, data_diff.py
├── tests/                    # unit, synthetic fixtures, benchmarks, integration
├── tasks/{plan,todo}.md
├── CLAUDE.md  CONSTRAINTS.md  Makefile  PROJECT.md  README.md
├── docker-compose.yml  pyproject.toml  uv.lock  .python-version
└── .gitignore  .env.example  .pre-commit-config.yaml
```

## Ways of working

- **1 task = 1 branch from `develop` = 1 PR into `develop`.** Branches `<type>/<name>`
  (`feat/`, `fix/`, `test/`, `docs/`, `ci/`, `chore/`, `infra/`, `perf/`).
- **Atomic commits** with a conventional prefix (`feat:`, `test:`, `docs:`…); in tasks
  with logic, the failing test's commit comes first, then the implementation.
- **Every PR updates the brain**: the component or concept note it touches, and
  `brain/phases/phase-1.md`. The PR template is there to remind you.
- **Only Piero approves and merges.** Claude creates branches, commits and PRs; never merges.
- **Skills by kind of work:** `test-driven-development` for all logic,
  `source-driven-development` for deltalake / dbt-duckdb / DuckDB-S3,
  `security-and-hardening` for PDFs and secrets, `performance-optimization` for benchmarks,
  `documentation-and-adrs` for the brain, and `ponytail-review` + `review` before opening every PR.
- **Phase release:** on close, a `develop → main` PR titled "Phase 1 — Foundation".

## Quality (detailed in CONSTRAINTS.md, task T4)

| Rule | Tool | Mode |
|---|---|---|
| Floor: lint, format, types, secrets, tests never disabled | ruff, mypy, gitleaks, floor-guard | **Blocks** from day 1 |
| Coverage ≥ 80% on new lines | pytest-cov + diff-cover | Warns until **2026-09-26**, then blocks |
| Security: nothing high-severity | pip-audit (dependencies), bandit (code) | Warns until 2026-09-26, then blocks |
| Performance: no more than 20% worse | pytest-benchmark (base vs PR on the same runner) | Warns until 2026-09-26, then blocks |
| Architecture: who can import whom | import-linter | Warns until 2026-09-26, then blocks |

## Definition of Done (for every task)

- [ ] The task's acceptance criteria are met.
- [ ] `make check-task` green locally and CI's blocking checks green.
- [ ] Behavior verified by running it, not just with tests.
- [ ] New tests fail without the change and pass with it.
- [ ] No real data or secrets in the diff.
- [ ] Brain note updated (and an ADR if a decision was made).
- [ ] `SETUP.md` kept current if the task adds libraries, programs, versions or env vars.
- [ ] `ponytail-review` and `review` with no pending findings.
- [ ] PR reviewed and merged by Piero.

## Tasks

Details, criteria and verification for each one live in [`todo.md`](todo.md).

**Block A — Repo foundation**
- T1 `chore/security-guards` — .gitignore, .env.example, pre-commit with gitleaks
- T2 `chore/python-project` — pyproject + uv + ruff/mypy/pytest + smoke test
- T3a `docs/brain-vault` — brain: structure, map, concepts, ADR 0001–0004
- T3b `docs/claude-md` — CLAUDE.md, PR template, updated PROJECT.md
- T4 `chore/constraints` — CONSTRAINTS.md, checks Makefile, floor-guard, import-linter
- T5 `ci/quality-gates` — CI workflow + required checks in the ruleset
- ✅ **Checkpoint A** — CI green on `develop`, brain browsable on GitHub

**Block B — Ingestion**
- T6 `feat/transaction-schema` — `Transaction` / `Statement` models per user and account (`account_id` HMAC) + normalization
- T7 `feat/file-hash` — SHA-256 of the file (file-level dedup)
- T8 `feat/reconciliation` — matching against declared balances and totals
- T9 `chore/pdf-layout-inspector` — masked dump of a PDF's layout
- T10 `test/bcp-synthetic-fixture` — BCP-style synthetic PDF generator
- T11 `feat/parser-bcp` — BCP parser + password unlocking
- T11b `feat/ocr-fallback` — OCR with Tesseract for scanned pages
- T12 `feat/dispatcher-cli` — content-based bank detection + `pfp parse --user` CLI
- T12b `feat/inbox-organizer` — inbox: content-based duplicate detection and filing by user, bank, account and period
- ✅ **Checkpoint B** — a real BCP PDF parses and reconciles locally

**Block C — Lakehouse**
- T13 `infra/s3-local` — docker-compose with SeaweedFS + bucket, isolatable per project (`make poc-up` / `poc-down`)
- T14 `feat/bronze-writer` — bronze in Delta partitioned by user (transactions, statements, files) + `pfp ingest`
- T15 `perf/benchmarks` — parsing and write benchmarks + CI job
- ✅ **Checkpoint C** — `pfp ingest` end-to-end; re-ingesting doesn't duplicate

**Block D — Transformation**
- T16 `feat/dbt-silver` — dbt-duckdb project, bronze source, silver model + tests (including balance continuity)
- T17 `ci/ephemeral-integration` — impact-based ephemeral environment in CI: per-PR compose + synthetic ingestion + `dbt build --select @state:modified` + sqlfluff + teardown; `make poc` locally
- T17b `ci/pr-data-diff` — base-vs-PR data comparison, published in the job summary
- ✅ **Checkpoint D** — `dbt build` green locally and in CI; every PR shows its effect on the data

**Block E — Second bank and close**
- T18 `feat/parser-scotiabank` — fixture + Scotiabank parser
- T18b `feat/inter-account-reconciliation` — matching transfers between accounts of the same user
- T19 `docs/phase-1-close` — README, brain kept current, turn on blocking for numeric rules
- ✅ **Final checkpoint** → `develop → main` release PR

## Ephemeral environments (ADR 0007)

Every PR that touches data gets tested on a temporary platform that's created, used, and torn down:

1. **Spin up**, only if the change affects data (ADR 0008) — `docker compose -p pfp-pr-<n> up -d --wait` (locally: `make poc-up`).
   The project name isolates containers, networks and volumes.
2. **Run** — ingestion and transformation with **synthetic** data in CI; with your
   **real PDFs only locally** (`make poc`), showing only pass/fail and reconciliation differences.
3. **Compare** — the same run against the base branch and the PR's; the differences
   (rows per model, schema, values) get published in the job summary.
4. **Save logs and always tear down** — first `docker compose logs` and dbt's artifacts get
   uploaded as job artifacts; then `docker compose -p pfp-pr-<n> down -v`, even on failure (`if: always()`).

These jobs use no secrets, so they work the same way for PRs from forks. Cloud
environments (Phase 4) only run on branches of this repo, always get torn down, and carry an expiry.

| Phase | What gets tested in the ephemeral environment | Where it's planned |
|---|---|---|
| 1 | Synthetic ingestion (re-ingesting doesn't duplicate) + `dbt build` + base-vs-PR comparison | T13, T17, T17b |
| 1 | Base-vs-PR performance on the same runner | T15 |
| 2 | The full Dagster pipeline and its checks | Phase 2 plan |
| 3 | Training on synthetic data (temporary MLflow) and metrics vs. the base model | Phase 3 plan |
| 3 and 5 | FastAPI and Streamlit in containers + smoke tests | Phase 3 and 5 plans |
| 4 | `terraform plan` on every PR; create and destroy real infrastructure only on request | Phase 4 plan |

## Impact-based CI (ADR 0008)

Every PR is evaluated by what it touches and what depends on it, not the whole project:

| What changes | What gets evaluated, on top of the cheap checks |
|---|---|
| Docs only (`*.md`, `brain/`) | Nothing else |
| `ingestion/` or `lakehouse/` | Benchmarks + ephemeral environment with a full `dbt build` (changes what reaches bronze) |
| `dbt/` | Ephemeral environment with `dbt build --select @state:modified` |
| `pyproject.toml`, `uv.lock`, `docker-compose.yml`, `.github/` | Everything |

- **Cheap checks always run in full** (ruff, mypy, unit pytest, gitleaks, pip-audit, bandit):
  they take seconds, and mypy needs the whole project to see when a change breaks whoever imports it.
- **dbt:** `dbt parse` on the base commit generates the comparison manifest with no database
  connection; the PR builds `@state:modified`: what changed, everything that depends on it, and
  the ancestors needed to build it in the empty environment.
- **Safety net:** everything runs in full on every push to `develop` and once a week, in case
  the map misses a relationship.
- **How a job gets skipped:** a `changes` job computes the affected areas via `git diff`
  against the base, and each expensive job has its own `if`. Never with workflow-level `paths`
  filters: a filtered workflow leaves required checks stuck on "Pending" and blocks the merge.
  And since a skipped job counts as successful, only what the change doesn't affect gets
  skipped — never a control like `branch-policy`.

## Users, accounts and integral reconciliation (ADR 0005 and 0009)

One install serves several users, and each one can hold several accounts, even at the same bank.

- **Content rules, not the file name.** The parser reads the bank, the account and the
  period from the PDF; the file is recognized by its hash and its name is never stored (it
  can contain account numbers).
- **User (`user_id`)** on all data: comes from the ingestion context (`pfp ingest --user`,
  defaulting to `PFP_USER`), never from the PDF. The lake is partitioned by `user_id`: deleting
  someone's data means dropping their partition.
- **Inbox and standardized archive (T12b).** PDFs get dropped with any name into
  `~/finance-data/inbox/<user>/`. When processed, each one is recognized by its hash and its
  content and moved to `~/finance-data/raw/<user>/<bank>/<last4>-<id6>/<start>_<end>.pdf`
  (id6 = the first 6 characters of `account_id`, so two accounts with the same last 4 digits
  don't collide). A duplicate goes to `_duplicates/` and anything unrecognized goes to
  `_needs_review/`, with a report saying what to do. A file is never deleted.
- **Account (`account_id`)**: HMAC-SHA256 of the bank and the full number with the
  `PFP_ACCOUNT_KEY` secret from `.env`, plus the last 4 digits for display. The full number
  only exists in memory during parsing.

**Integral reconciliation**, at three levels:

| Level | What it checks | Where |
|---|---|---|
| Statement | Opening balance + movements = closing balance, and the declared totals | T8 |
| Continuity | A period's closing balance is the next period's opening balance, per account; catches missing statements | T16 |
| Between accounts | Every transfer between accounts of the same user has its counterpart, and never counts as an expense or income | T18b |

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Designing parsers with real PDFs exposes personal data (what I read leaves your machine) | High | T9: a layout dump with digits and text masked; I never read a real PDF unmasked without your OK |
| The synthetic PDF doesn't reflect the real one | Medium | Local tests marked `real_pdf` against your PDFs + reconciliation as a safety net |
| MinIO unmaintained | High | SeaweedFS (ADR 0003); standard S3 API, switching servers means switching an endpoint |
| DuckDB reading Delta on local S3 (endpoint, path-style, SSL) | Medium | A minimal test at the start of T16, before modeling |
| delta-rs on S3 with no locking | Low in Phase 1 (a single writer) | Documented in ADR 0006; revisited in Phase 2 with Dagster |
| Password-protected PDFs, at least one scanned (confirmed) | High | pikepdf + password in `.env`; T9 detects pages with no text; OCR with Tesseract (T11b); reconciliation catches OCR misreads |
| Noisy benchmarks in CI | Medium | Base and PR on the same runner, a 20% margin, 2 weeks in warn mode |
| An ephemeral environment stays alive (containers, volumes) or stretches CI too long | Low | Per-PR project name, `down -v` with `if: always()` and `timeout-minutes` on the job; T17's verification checks that nothing's left behind |
| The impact map misses an indirect relationship and skips a job that should have run | Medium | Cheap checks always run in full; full run on push to `develop` and weekly; changes to dependencies, compose or CI run everything |
| `PFP_ACCOUNT_KEY` gets lost and every `account_id` changes | Medium | Back it up outside the repo (a password manager), documented in SETUP.md in T6; changing the key requires reprocessing from the PDFs |
| Cross-bank transfers with a fee, a day's lag, or a different currency | Medium | Configurable day window and tolerance; anything that doesn't match gets flagged for review, never dropped; cross-currency stays out of T18b |
| A joint account (two users, the same account) | Low | Open question: today each user would get their own copy; revisited if the case comes up |
| A PDF holds several accounts | Medium | The parser returns one `Statement` per account; the file is saved once, in `<bank>/_multi-account/`; T9's dump confirms whether this happens |
| The bank regenerates a period's PDF (different bytes) | Low | Filed as a second version (`_v2`) with a warning; the business key keeps movements from duplicating |
| 7 GB of RAM for Phase 2 (Spark + catalog) | Medium | Evaluated when planning Phase 2 (`.wslconfig`, lighter alternatives) |
| `gh` 2.46 fails on `gh pr edit` | Low | Use the REST API (`gh api`) |

## Confirmed decisions (2026-09-12)

1. **S3 storage:** SeaweedFS.
2. **Privacy:** parsers are designed from T9's masked dump; Claude never reads real PDFs unmasked.
3. **PDFs:** password-protected, and at least one is scanned → OCR enters Phase 1 (T11b).
4. **Location:** inbox `~/finance-data/inbox/<user>/` with any name, and a standardized archive
   `~/finance-data/raw/<user>/<bank>/<account>/` (previously `raw/{bcp,scotiabank}/`), outside
   the repo and readable only by its owner.
5. **Users and accounts:** several users in one install; an account identified by an HMAC
   with a key + the last 4 digits; inter-account reconciliation in Phase 1 (T18b).

## Open questions

1. **Date to switch from warn to block:** proposed 2026-09-26.
2. **Which PDFs or pages are scanned:** answered by T9's inspector.
