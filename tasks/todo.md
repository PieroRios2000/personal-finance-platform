# Tasks — Phase 1: Foundation

> Context, decisions and risks in [`plan.md`](plan.md). Each task = 1 branch from `develop` = 1 PR.
> Every task also satisfies the **Definition of Done** in `plan.md`.

## Environment prerequisites (no PR generated)

- [x] Install `uv` at the user level (no sudo) and Python 3.12 managed by uv.
- [x] Docker reachable without sudo from WSL (restart WSL after joining the `docker` group).
- [ ] Real PDFs in the inbox `~/finance-data/inbox/<user>/`, under any name (ADR 0009; they used to live in `raw/{bcp,scotiabank}/`); T12b files them.
- [x] Tesseract OCR (`sudo apt install tesseract-ocr tesseract-ocr-spa`) before T11b.

---

## Block A — Repo foundation

### T1: Security guards — `chore/security-guards`

**Description:** Before any code, keep data or secrets from ever reaching Git.

**Acceptance criteria:**
- [x] `*.pdf`, `.env`, `*.duckdb`, `data/` and the local lake are ignored.
- [x] pre-commit with gitleaks (+ detect-private-key, check-added-large-files) installed.
- [x] `.env.example` documents the variables with no real values.

**Verification:**
- [x] `git check-ignore -v x.pdf .env` confirms the rules.
- [x] A fake test secret gets blocked by the hook (and discarded).
- [x] `pre-commit run --all-files` is green.

**Dependencies:** none · **Files:** `.gitignore`, `.env.example`, `.pre-commit-config.yaml` · **Size:** S · **Skill:** security-and-hardening

### T2: Python project — `chore/python-project`

**Description:** A project with uv and Python 3.12, quality tools configured, and a smoke test.

**Acceptance criteria:**
- [x] `pyproject.toml` (requires-python 3.12, pydantic; dev: pytest, pytest-cov, ruff, mypy), `.python-version`, `uv.lock`.
- [x] `ingestion/` and `lakehouse/` packages importable; ruff in pre-commit.
- [x] ruff, mypy (strict) and pytest configured in `pyproject.toml`.

**Verification:**
- [x] `uv sync` clean; `uv run ruff check .`, `uv run mypy .`, `uv run pytest` all green.

**Dependencies:** T1 · **Files:** `pyproject.toml`, `uv.lock`, `.python-version`, `ingestion/__init__.py`, `lakehouse/__init__.py`, `tests/test_smoke.py` · **Size:** S

### T3a: Project brain — `docs/brain-vault`

**Description:** A linked Markdown vault explaining the context and how concepts, components, decisions and phases relate.

**Acceptance criteria:**
- [x] `brain/README.md` with a Mermaid map, an index, and note conventions (frontmatter `type` and `phase`; relationships as relative links in a "Related" section).
- [x] Templates in `brain/_templates/`; base concepts (medallion, idempotency, business key, reconciliation, file-level dedup).
- [x] ADR 0001–0004 in `brain/decisions/` and `brain/phases/phase-1.md`, linking this plan.

**Verification:**
- [x] Links navigate in the PR's GitHub view, and the Mermaid diagram renders.
- [x] No broken links (checked with a script or lychee locally).

**Dependencies:** T2 · **Files:** `brain/**` · **Size:** M (Markdown only) · **Skill:** documentation-and-adrs

### T3b: Context for agents and PRs — `docs/claude-md`

**Description:** A CLAUDE.md pointing to the brain and the rules; a PR template; PROJECT.md kept current with the decisions.

**Acceptance criteria:**
- [x] `CLAUDE.md`: branch flow, "only Piero merges", data never in Git, read `brain/` and `CONSTRAINTS.md`.
- [x] `.github/pull_request_template.md` with a checklist (DoD + brain note).
- [x] `PROJECT.md` reflects the BCP/Scotiabank banks, S3 storage and Phase 1's stack.

**Verification:**
- [ ] A test PR (this one) shows the template; CLAUDE.md loads in a new session.

**Dependencies:** T3a · **Files:** `CLAUDE.md`, `.github/pull_request_template.md`, `PROJECT.md` · **Size:** S · **Skill:** context-engineering

### T4: Quality bar — `chore/constraints`

**Description:** CONSTRAINTS.md with rules, numbers and reasons, and the commands that check them.

**Acceptance criteria:**
- [x] `CONSTRAINTS.md` with the floor, a table of numeric rules (command + where it runs), measured metrics and exceptions.
- [x] `Makefile` with `check-fast` (< 5 s), `check-task` (< 90 s) and `check-full` (CI).
- [x] floor-guard adapted, plus import-linter contracts for `ingestion` / `lakehouse`.

**Verification:**
- [x] `make check-full` green on the current code.
- [x] floor-guard catches a `# type: ignore` injected into a test diff.

**Dependencies:** T2 · **Files:** `CONSTRAINTS.md`, `Makefile`, `scripts/floor_guard*`, `pyproject.toml` · **Size:** M · **Skill:** constraint-driven-development

### T5: Quality CI — `ci/quality-gates`

**Description:** A workflow that runs the rules on every PR, blocking or warning per CONSTRAINTS.md.

**Acceptance criteria:**
- [x] Jobs: `lint-types`, `tests` (+ diff-cover), `security` (gitleaks, pip-audit, bandit), `architecture`, `floor-guard`.
- [x] Numeric rules with `continue-on-error` until 2026-09-26; actions pinned by SHA and `sha_pinning_required` turned on.
- [x] Blocking checks added as required in the `protect-main-develop` ruleset.
- [x] Readable failures: annotations on the exact PR line (ruff and mypy in GitHub's format), a pytest summary in the job, and a "Reviewing CI" section in `SETUP.md` (`gh pr checks`, `gh run view`, the job's log via `gh api …/actions/jobs/<id>/logs`, `gh run rerun --failed`).

**Verification:**
- [x] A PR with a mypy error (not ruff — ruff is a pre-commit hook, so a real ruff violation can't reach a commit without `--no-verify`, which CLAUDE.md forbids; mypy isn't a local hook) fails and stays `BLOCKED`; the same PR, reverted, passes.
- [x] That error shows up annotated on the file's exact line inside the PR (`ingestion/__init__.py:5`).

**Dependencies:** T4 · **Files:** `.github/workflows/ci.yml`, `SETUP.md` · **Size:** M · **Skill:** ci-cd-and-automation

### ✅ Checkpoint A
- [ ] CI green on `develop` · [ ] pre-commit works locally · [ ] brain browsable · [ ] reviewed with Piero

---

## Block B — Ingestion

### T6: Transaction schema — `feat/transaction-schema`

**Description:** pydantic models shared across all banks, per user and per account (ADR 0005 and 0009).

**Acceptance criteria:**
- [x] `Transaction` (`user_id`, bank, `account_id`, last 4 of the account, date, description, `Decimal` amount to 2 places, PEN/USD currency, file sha).
- [x] `Statement` (`user_id`, bank, `account_id`, last 4, period, opening/closing balances, declared totals, transactions).
- [x] `hash_account(bank, number)`: HMAC-SHA256 with the `PFP_ACCOUNT_KEY` secret; a clear error if the key is missing. `PFP_ACCOUNT_KEY` and `PFP_USER` in `.env.example` and SETUP.md, including how to generate and back up the key.
- [x] `normalize_description()` is stable (trim, uppercase, no filler codes).
- [x] ADR 0005 and ADR 0009 written in `brain/decisions/`.

**Verification:**
- [x] TDD tests: invalid amounts, unknown currency and a full account number are rejected; same bank and number → same `account_id`; a different bank or key → a different one.

**Dependencies:** T5 · **Files:** `ingestion/schema.py`, `tests/test_schema.py`, `.env.example`, `SETUP.md` · **Size:** M · **Skill:** test-driven-development

### T7: File hash — `feat/file-hash`

**Description:** SHA-256 of the PDF's content, so the same file never gets reprocessed.

**Acceptance criteria:**
- [x] `file_sha256(path)` using `hashlib.file_digest` (streaming, stdlib).
- [x] The same content under a different name → the same hash.

**Verification:**
- [x] Tests with temporary files.

**Dependencies:** T5 · **Files:** `ingestion/dedup.py`, `tests/test_dedup.py` · **Size:** XS

### T8: Reconciliation — `feat/reconciliation`

**Description:** Verify that what's extracted matches what the PDF declares.

**Acceptance criteria:**
- [x] `reconcile(statement)`: opening balance + Σ amounts == closing balance, plus the charge/credit totals when present.
- [x] `ReconciliationError` with the expected value, the actual one, and the difference.

**Verification:**
- [x] Tests: an exact match, a 0.01 mismatch, a statement with no transactions.

**Dependencies:** T6 · **Files:** `ingestion/reconciliation.py`, `tests/test_reconciliation.py` · **Size:** S · **Skill:** test-driven-development

### T9: Masked layout inspector — `chore/pdf-layout-inspector`

**Description:** A local script that describes a PDF's structure without exposing personal data, for designing parsers and fixtures.

**Acceptance criteria:**
- [x] Opens PDFs with bytes before `%PDF-` (BCP's starts with `$BOP$`) and unlocks them with the password from `.env`; prints lines and columns with positions, per page.
- [x] Digits → `9`; text outside a list of known headers → masked.
- [x] Reports whether the PDF is encrypted and which pages have no text layer (scanned).

**Verification:**
- [ ] Piero runs it on a real PDF and confirms the output holds no personal data before sharing it.

**Dependencies:** T2 · **Files:** `scripts/inspect_pdf_layout.py`, `tests/test_inspect_pdf_layout.py` · **Size:** S · **Skill:** security-and-hardening

### T10: BCP synthetic fixture — `test/bcp-synthetic-fixture`

**Description:** Generate a fake PDF with BCP's layout inside the tests (no binary files in Git).

**Acceptance criteria:**
- [x] A generator (fpdf2, dev dependency) that produces a fictional BCP statement with coherent totals.
- [x] A pytest fixture that creates it in `tmp_path`.

**Verification:**
- [ ] T9's dump on the synthetic PDF matches the real one structurally. No masked dump of a
      real statement was available this session, so this is checked only against a plausible,
      well-formed shape (headers unmasked, amounts/dates masked, columns aligned) plus an
      automated test — see the PR for the actual dump. Full comparison stays open until Piero
      shares T9's dump of a real statement (before or during T11).

**Dependencies:** T9 · **Files:** `tests/fixtures/synthetic_pdfs.py`, `tests/conftest.py` · **Size:** S

### T11: BCP parser — `feat/parser-bcp`

**Description:** Turn a BCP PDF into a reconciled `Statement`.

**Acceptance criteria:**
- [x] `parsers/base.py` (a `detect` + `parse` protocol) and `parsers/bcp.py` with pdfplumber; unlocking with pikepdf.
- [x] Bank, account number and period come from the PDF's content, never the file name; the full number only lives in memory to compute `account_id`.
- [x] The synthetic parser reconciles; `real_pdf` tests (deselected by default) reconcile against your PDFs.

**Verification:**
- [x] `uv run pytest` green; `uv run pytest -m real_pdf` green on your machine (pending: needs your real PDFs + `BCP_PDF_PASSWORD`, skips gracefully without them — see the BCP parser brain note).

**Dependencies:** T6, T8, T10 · **Files:** `ingestion/parsers/{__init__,base,bcp}.py`, `tests/parsers/test_bcp.py` · **Size:** M · **Skill:** test-driven-development

### T11b: OCR for scanned pages — `feat/ocr-fallback`

**Description:** Some PDFs are scanned; when a page has no text layer, get its text via OCR.

**Acceptance criteria:**
- [x] `ingestion/ocr.py`: if a page's `extract_text()` comes back empty, render it at 300 dpi (pdfplumber) and read it with Tesseract in Spanish.
- [x] Parsers receive the text without knowing whether it came from OCR; reconciliation catches read errors.
- [x] CI installs Tesseract and tests against a rasterized synthetic PDF.

**Verification:**
- [ ] `uv run pytest -m real_pdf` reconciles the real scanned PDF on your machine. (Verified end to end against a synthetic scanned page; needs your real scanned PDF to close out.)

**Dependencies:** T9, T11 · **Files:** `ingestion/ocr.py`, `tests/test_ocr.py`, `.github/workflows/ci.yml` · **Size:** M · **Skill:** source-driven-development

### T12: Dispatcher and CLI — `feat/dispatcher-cli`

**Description:** Detect a PDF's bank from its content and expose `pfp parse <pdf>`.

**Acceptance criteria:**
- [x] `dispatcher.py` picks the parser via `detect` (content, not the file name); a clear error if no parser recognizes it.
- [x] An argparse CLI (`[project.scripts] pfp`): `--user` (defaulting to `PFP_USER`); prints a summary (bank, last 4, period) and the reconciliation result.

**Verification:**
- [ ] `uv run pfp parse <real BCP pdf>` shows the summary and "reconciliation OK". (Verified against a synthetic PDF; needs your real PDF + `BCP_PDF_PASSWORD` to close out.)
- [x] The same synthetic PDF under an arbitrary name gives the same result.

**Dependencies:** T7, T11 · **Files:** `ingestion/dispatcher.py`, `ingestion/cli.py`, tests · **Size:** S

### T12b: Inbox and archive — `feat/inbox-organizer`

**Description:** Process a folder of PDFs under any name: detect duplicates by content and file each one in its standard place by user, bank, account and period (ADR 0009).

**Acceptance criteria:**
- [ ] `pfp organize --user <u>` walks `~/finance-data/inbox/<u>/` (a configurable path). For each PDF: hash it (T7); if the user already has it, move it to `_duplicates/`; otherwise read the bank, account and period from its content (T12) and move it to `raw/<u>/<bank>/<last4>-<id6>/<start>_<end>.pdf`.
- [ ] Anything unreadable (unknown bank, no account or period, wrong password) goes to `_needs_review/`, with a report saying why and what to do.
- [ ] The same account and period with different content (a regenerated PDF) → saved as `_v2` with a warning. A PDF holding several accounts → `<bank>/_multi-account/`.
- [ ] Never deletes a file. The report shows, per account (bank and last 4), which periods are archived and which months are missing.

**Verification:**
- [ ] Three synthetic PDFs sharing a name (`EECC.pdf`, `EECC (1).pdf`, `EECC (2).pdf`) from three different accounts end up in three different folders; a repeat lands in `_duplicates/` and an unreadable one in `_needs_review/`.
- [ ] On your machine, with your real PDFs in the inbox, the report classifies all of them without showing full numbers or amounts.

**Dependencies:** T6, T7, T12 · **Files:** `ingestion/organizer.py`, `ingestion/cli.py`, tests · **Size:** M · **Skill:** test-driven-development

### ✅ Checkpoint B
- [ ] A real BCP PDF parses and reconciles locally · [ ] the inbox files your PDFs by bank and account · [ ] CI green · [ ] reviewed with Piero

---

## Block C — Lakehouse

### T13: Local S3 — `infra/s3-local`

**Description:** Bring up S3-compatible storage with a single command, in isolated environments that get created and torn down (ADR 0007).

**Acceptance criteria:**
- [x] `docker-compose.yml` with SeaweedFS (pinned tag), a healthcheck, and a `lakehouse` bucket created on startup.
- [x] No fixed `container_name`, and the host port configurable via a variable, so several projects (`-p <name>`) can coexist.
- [x] Credentials only from `.env`; ADR 0003 updated with the final configuration, and ADR 0007 created.
- [x] `make poc-up` / `make poc-down` (`up -d --wait` and `down -v` with a project name).

**Verification:**
- [x] `docker compose up -d` → the service is `healthy`; writing and reading a test object works.
- [x] Two projects running at the same time don't collide; after `make poc-down` no containers or volumes from the project remain.

**Dependencies:** T5 · **Files:** `docker-compose.yml`, `.env.example`, `Makefile` · **Size:** S

### T14: Bronze writer — `feat/bronze-writer`

**Description:** Save transactions to Delta (append-only) and register ingested files; `pfp ingest`.

**Acceptance criteria:**
- [ ] `lakehouse/` writes `bronze/transactions`, `bronze/statements` (period, balances and totals for each statement) and `bronze/ingested_files` with `deltalake`, partitioned by `user_id`, located via `LAKEHOUSE_URI`.
- [ ] `pfp ingest --user <u>`: organizes the inbox (T12b) and, for every new file, parses → reconciles → writes to bronze; if (user, hash) already exists, it's skipped. The original file name is never stored.
- [ ] Ingesting the same PDF twice never adds rows.

**Verification:**
- [ ] Tests with the lake in `tmp_path`; an integration test (`integration` marker) against local S3.
- [ ] Two users with synthetic PDFs end up in separate partitions; deleting one doesn't affect the other.

**Dependencies:** T12b, T13 · **Files:** `lakehouse/{storage,bronze}.py`, `ingestion/cli.py`, tests · **Size:** M · **Skill:** source-driven-development

### T15: Benchmarks — `perf/benchmarks`

**Description:** Measure parsing and writes, and warn if a PR makes them worse.

**Acceptance criteria:**
- [ ] Parsing benchmarks (an N-page synthetic PDF) and a bronze append.
- [ ] A CI job comparing base vs PR on the same runner (`--benchmark-compare-fail=mean:20%`), in warn mode.
- [ ] A `changes` job (ADR 0008): affected areas per `git diff` against the base and the impact map; benchmarks run only if `ingestion/`, `lakehouse/` or the dependencies change. Everything runs on push to `develop` and once a week.
- [ ] Current values noted in CONSTRAINTS.md ("Measured"), and ADR 0008 created in `brain/decisions/`.

**Verification:**
- [ ] A PR with an artificial `sleep` triggers the warning (and gets discarded).
- [ ] A PR that only touches docs skips the benchmarks and stays mergeable; one that touches `ingestion/` runs them.

**Dependencies:** T14 · **Files:** `tests/benchmarks/*`, `.github/workflows/ci.yml`, `CONSTRAINTS.md` · **Size:** S · **Skill:** performance-optimization

### ✅ Checkpoint C
- [ ] Real `pfp ingest` end-to-end · [ ] re-ingesting doesn't duplicate · [ ] reviewed with Piero

---

## Block D — Transformation

### T16: dbt silver — `feat/dbt-silver`

**Description:** A dbt-duckdb project reading bronze (Delta on S3) and producing silver with tests.

**Acceptance criteria:**
- [ ] A minimal `delta_scan` read test against local S3, before any modeling.
- [ ] `bronze.transactions` and `bronze.statements` sources, `silver/transactions` model (types, normalized description, currency, account).
- [ ] dbt tests (not_null, accepted_values for currency), a continuity test (a period's closing balance = the next period's opening balance, per user and account), and sqlfluff config.

**Verification:**
- [ ] `uv run dbt build` and `uv run sqlfluff lint dbt/models` green locally.
- [ ] A synthetic statement missing between two periods fails the continuity test.

**Dependencies:** T14 · **Files:** `dbt/**`, `pyproject.toml` · **Size:** M · **Skill:** source-driven-development

### T17: Ephemeral integration environment — `ci/ephemeral-integration`

**Description:** On every PR, create the temporary platform, ingest synthetic data, run dbt, and tear it down (ADR 0007). The same thing locally with your real PDFs.

**Acceptance criteria:**
- [ ] CI job: `docker compose -p pfp-pr-<n> up -d --wait` → `pfp ingest` the synthetic fixture twice (the second adds 0 rows) → `dbt build` → `sqlfluff lint` → `down -v` with `if: always()`.
- [ ] Impact-based (ADR 0008): the environment only spins up if `ingestion/`, `lakehouse/`, `dbt/` or the dependencies change; `dbt parse` on the base commit generates the manifest, and the PR builds `@state:modified`; if `ingestion/` or `lakehouse/` change, a full `dbt build`.
- [ ] `integration` tests run in this job; no secrets, with `timeout-minutes`.
- [ ] Before tearing down, save `docker compose logs` and dbt's artifacts (`target/run_results.json`, `logs/dbt.log`) as a job artifact (`if: always()`, short retention), so a failure can still be reviewed once the environment is gone.
- [ ] `make poc`: the same flow locally with your real PDFs; prints only pass/fail and reconciliation differences, and tears the environment down at the end.

**Verification:**
- [ ] The job is green; breaking a dbt test on purpose turns it red (and gets discarded).
- [ ] Once the job finishes, green or red, no containers or volumes from the project remain.
- [ ] `make poc` green on your machine and leaves nothing behind.
- [ ] A PR that changes a silver model only builds that model, its descendants, and the ancestors needed (visible in dbt's log).

**Dependencies:** T15, T16 · **Files:** `.github/workflows/ci.yml`, `Makefile` · **Size:** M · **Skill:** ci-cd-and-automation

### T17b: Base-vs-PR comparison — `ci/pr-data-diff`

**Description:** Show what changes in the data on every PR: the same ephemeral run against the base branch and against the PR's, compared.

**Acceptance criteria:**
- [ ] The job runs T17's flow for the base commit and for the PR's, with the same synthetic data in separate locations (a lake prefix and a DuckDB file per run).
- [ ] `scripts/data_diff.py` compares the models built in the run using DuckDB: rows per model, columns and types, and differing rows (`EXCEPT` both ways, with a limited sample).
- [ ] Results in Markdown in the job summary (`$GITHUB_STEP_SUMMARY`); warn mode, doesn't block.

**Verification:**
- [ ] TDD tests for the script with two small DuckDB databases.
- [ ] A PR that changes a silver model shows the difference; one with no model changes shows "no changes".

**Dependencies:** T17 · **Files:** `scripts/data_diff.py`, `tests/test_data_diff.py`, `.github/workflows/ci.yml` · **Size:** M · **Skill:** test-driven-development

### ✅ Checkpoint D
- [ ] `dbt build` green locally and in CI · [ ] the ephemeral environment always gets torn down · [ ] a PR shows its data diff · [ ] a docs-only PR doesn't spin up the environment · [ ] reviewed with Piero

---

## Block E — Second bank and close

### T18: Scotiabank parser — `feat/parser-scotiabank`

**Description:** A second bank: proves the parser and dispatcher design scales.

**Acceptance criteria:**
- [ ] A masked layout (T9), a synthetic fixture, and `parsers/scotiabank.py` registered in the dispatcher.
- [ ] Like T11: bank, account and period come from the PDF's content, and the inbox (T12b) files its PDFs.
- [ ] Synthetic tests in CI and `real_pdf` locally both reconcile.

**Verification:**
- [ ] `uv run pfp ingest <real Scotiabank pdf>` writes to bronze, and `dbt build` includes it in silver.

**Dependencies:** T11b, T12, T14 · **Files:** `ingestion/parsers/scotiabank.py`, `tests/fixtures/…`, `tests/parsers/test_scotiabank.py` · **Size:** M · **Skill:** test-driven-development

### T18b: Inter-account reconciliation — `feat/inter-account-reconciliation`

**Description:** Match transfers between accounts of the same user, so they never count as an expense or income, and flag the ones with no counterpart (ADR 0009).

**Acceptance criteria:**
- [ ] A dbt model `silver/internal_transfers`: matches an outflow and an inflow from the same user, on different accounts, in the same currency, for the same amount (configurable tolerance, default 0), within N days or fewer (default 3). Every movement is in at most one pair.
- [ ] `silver/transactions` flags `is_internal_transfer`; unmatched candidates land in `silver/unmatched_transfers` for review, never dropped.
- [ ] Cross-currency transfers stay out of this task and show up as unmatched.

**Verification:**
- [ ] With synthetic BCP and Scotiabank data and a transfer between them, it comes back matched; removing the inflow makes it show up in `unmatched_transfers`.
- [ ] `make poc` against your real PDFs shows only how many matched and how many didn't, with no amounts.

**Dependencies:** T16, T18 · **Files:** `dbt/models/silver/**`, tests · **Size:** M · **Skill:** test-driven-development

### T19: Phase close — `docs/phase-1-close`

**Description:** Leave the phase presentable and turn on blocking for the numeric rules.

**Acceptance criteria:**
- [ ] README: what this is, a diagram, how to run it, the Azure ↔ open-source equivalence.
- [ ] Brain kept current (phase-1 closed, Mermaid map, components).
- [ ] Numeric rules switch to blocking (if 2026-09-26 has passed).

**Verification:**
- [ ] Clone the repo into a clean folder and follow the README through to `dbt build` with no missing steps.

**Dependencies:** T17b, T18b · **Files:** `README.md`, `brain/**`, `.github/workflows/ci.yml` · **Size:** S

### ✅ Final checkpoint
- [ ] All criteria met · [ ] integral reconciliation green (statement, continuity and between accounts) · [ ] `develop → main` release PR "Phase 1 — Foundation" · [ ] merged by Piero
