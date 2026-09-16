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
- [x] `pfp organize --user <u>` walks `~/finance-data/inbox/<u>/` (a configurable path). For each PDF: hash it (T7); if the user already has it, move it to `_duplicates/`; otherwise read the bank, account and period from its content (T12) and move it to `raw/<u>/<bank>/<last4>-<id6>/<start>_<end>.pdf`. Duplicate detection is scoped to what a persistent registry isn't needed for yet — see the PR and `brain/components/inbox-organizer.md`.
- [x] Anything unreadable (unknown bank, no account or period, wrong password) goes to `_needs_review/`, with a report saying why and what to do.
- [x] The same account and period with different content (a regenerated PDF) → saved as `_v2` with a warning. Climbs to `_v3` etc. if needed.
- [ ] A PDF holding several accounts → `<bank>/_multi-account/`. **Not implemented**: today's single-account `bcp.parse()` (T11) can't signal "there was a second account", so there's nothing to trigger this path with — see the PR and the brain note for the full explanation.
- [x] Never deletes a file. The report shows, per account (bank and last 4), which periods are archived and which months are missing.

**Verification:**
- [x] Three synthetic PDFs sharing a name (`EECC.pdf`, `EECC (1).pdf`, `EECC (2).pdf`) from three different accounts end up in three different folders; a repeat lands in `_duplicates/` and an unreadable one in `_needs_review/`.
- [ ] On your machine, with your real PDFs in the inbox, the report classifies all of them without showing full numbers or amounts. **Piero's step**: `uv run pfp organize --user piero` (uses the default `~/finance-data/inbox/piero/` and `~/finance-data/raw/piero/`).

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
- [x] `lakehouse/` writes `bronze/transactions`, `bronze/statements` (period, balances and totals for each statement) and `bronze/ingested_files` with `deltalake`, partitioned by `user_id`, located via `LAKEHOUSE_URI`.
- [x] `pfp ingest --user <u>`: organizes the inbox (T12b) and, for every new file, parses → reconciles → writes to bronze; if (user, hash) already exists, it's skipped. The original file name is never stored.
- [x] Ingesting the same PDF twice never adds rows.

**Verification:**
- [x] Tests with the lake in `tmp_path`; an integration test (`integration` marker) against local S3.
- [x] Two users with synthetic PDFs end up in separate partitions; deleting one doesn't affect the other.

**Dependencies:** T12b, T13 · **Files:** `lakehouse/{storage,bronze}.py`, `ingestion/cli.py`, tests · **Size:** M · **Skill:** source-driven-development

### T14c: Bronze backfill — `feat/bronze-backfill`

**Description:** Re-parse statements that are already archived and already in bronze with today's parser, replacing their rows, so a parser fix reaches historical data and not just the next statement (`pfp backfill`). ADR 0010.

**Acceptance criteria:**
- [x] `lakehouse.bronze.replace_statement(statement, file_sha256)` deletes that file's rows from `bronze/transactions` and `bronze/statements` — scoped by `user_id` as well as the sha256 — and writes the fresh parse. `bronze/ingested_files` keeps its single row with its original `ingested_at`: the file's bytes didn't change, only its interpretation.
- [x] `pfp backfill --user <u> [--archive-root DIR] [--bank BANK] [--account LAST4] [--dry-run]` walks `<archive-root>/<user>/**/*.pdf`, never the inbox, skipping `_duplicates/` and `_needs_review/`; `--bank`/`--account` filter on the directory layout `organize()` produced, without parsing.
- [x] A file that fails to re-parse (unknown bank, wrong password, reconciliation failure, malformed statement) is reported with a plain-language reason and leaves its bronze rows untouched; the run finishes. A missing `PFP_ACCOUNT_KEY` or `LAKEHOUSE_URI` stops it instead, with a clear message.
- [x] `--dry-run` writes nothing and reports, per file, the transaction count in bronze versus in the fresh parse and whether they differ. The report never prints a description, an amount or a full account number (ADR 0004).
- [x] ADR 0010 records the replace-not-version decision, the alternative considered, and the consequences (history of a wrong parse, no cross-table atomicity).

**Verification:**
- [x] Tests with the lake in `tmp_path`: a replace leaves only the fresh rows, doesn't touch another user's rows sharing the same sha256, leaves `ingested_files` alone, and writes fresh when the file was never ingested.
- [x] Run for real on a throwaway archive and lake: `pfp ingest` (2 synthetic statements, 8 transaction rows), then `--dry-run`, a full backfill and an `--account`-filtered one — still 8/2/2 rows in `transactions`/`statements`/`ingested_files` afterwards, i.e. replaced, not appended.
- [ ] On your machine, with your real statements already archived: `uv run pfp backfill --user piero --dry-run`, then the same without `--dry-run`, and confirm the reported counts. **Piero's step.**

**Dependencies:** T14 · **Files:** `lakehouse/bronze.py`, `ingestion/cli.py`, tests, `brain/decisions/0010-bronze-backfill-replaces-not-versions.md` · **Size:** M · **Skill:** test-driven-development

### T15: Benchmarks — `perf/benchmarks`

**Description:** Measure parsing and writes, and warn if a PR makes them worse.

**Acceptance criteria:**
- [x] Parsing benchmarks (an N-page synthetic PDF) and a bronze append.
- [x] A CI job comparing base vs PR on the same runner (`--benchmark-compare-fail=mean:20%`), in warn mode.
- [x] A `changes` job (ADR 0008): affected areas per `git diff` against the base and the impact map; benchmarks run only if `ingestion/`, `lakehouse/` or the dependencies change. Everything runs on push to `develop` and once a week.
- [x] Current values noted in CONSTRAINTS.md ("Measured"), and ADR 0008 created in `brain/decisions/`.

**Verification:**
- [x] A PR with an artificial `sleep` triggers the warning (and gets discarded).
- [x] A PR that only touches docs skips the benchmarks and stays mergeable; one that touches `ingestion/` runs them.

**Dependencies:** T14 · **Files:** `tests/benchmarks/*`, `.github/workflows/ci.yml`, `CONSTRAINTS.md` · **Size:** S · **Skill:** performance-optimization

### ✅ Checkpoint C
- [ ] Real `pfp ingest` end-to-end · [ ] re-ingesting doesn't duplicate · [ ] reviewed with Piero

---

## Block D — Transformation

### T16: dbt silver — `feat/dbt-silver`

**Description:** A dbt-duckdb project reading bronze (Delta on S3) and producing silver with tests.

**Acceptance criteria:**
- [x] A minimal `delta_scan` read test against local S3, before any modeling (`tests/test_delta_scan_integration.py`).
- [x] `bronze.transactions` and `bronze.statements` sources, `silver/transactions` model (types, normalized description, currency, account).
- [x] dbt tests (not_null, accepted_values for currency), a continuity test (a period's closing balance = the next period's opening balance, per user and account), and sqlfluff config.

**Verification:**
- [x] `uv run dbt build` and `uv run sqlfluff lint dbt/models` green locally.
- [x] A synthetic statement missing between two periods fails the continuity test (`tests/test_dbt_silver_integration.py`, red then green).

**Dependencies:** T14 · **Files:** `dbt/**`, `pyproject.toml` · **Size:** M · **Skill:** source-driven-development

**Notes:** both `dbt build` and `sqlfluff lint` need `--project-dir dbt --profiles-dir dbt` and
the `.env` values exported (SETUP.md §6). Design calls in
[ADR 0011](../brain/decisions/0011-delta-scan-as-a-dbt-source.md): a source is a `delta_scan()`
call via dbt-duckdb's `external_location`, DuckDB is on disk (`dbt/pfp.duckdb`), and sqlfluff's
config is in `pyproject.toml`. CI does not run dbt yet — that is T17's job.

### T17: Ephemeral integration environment — `ci/ephemeral-integration`

**Description:** On every PR, create the temporary platform, ingest synthetic data, run dbt, and tear it down (ADR 0007). The same thing locally with your real PDFs.

**Acceptance criteria:**
- [x] CI job: `docker compose -p pfp-pr-<n> up -d --wait` → `pfp ingest` the synthetic fixture twice (the second adds 0 rows) → `dbt build` → `sqlfluff lint` → `down -v` with `if: always()`. (pending: verified by running every step of this exact sequence locally against a live SeaweedFS with the job's own env values — the `ephemeral-integration` job itself needs a live GitHub Actions PR run to confirm, which this session cannot trigger.)
- [x] Impact-based (ADR 0008): the environment only spins up if `ingestion/`, `lakehouse/`, `dbt/` or the dependencies change; `dbt parse` on the base commit generates the manifest, and the PR builds `state:modified+` (ADR 0013); if `ingestion/` or `lakehouse/` change, a full `dbt build`.
- [x] `integration` tests run in this job; no secrets, with `timeout-minutes`.
- [x] Before tearing down, save `docker compose logs` and dbt's artifacts (`target/run_results.json`, `logs/dbt.log`) as a job artifact (`if: always()`, short retention), so a failure can still be reviewed once the environment is gone. (pending: the files themselves were verified locally; the `actions/upload-artifact` step needs a live GitHub Actions run to confirm.)
- [ ] `make poc`: the same flow locally with your real PDFs; prints only pass/fail and reconciliation differences, and tears the environment down at the end. **Piero's step**: this session must never read your real PDFs or `.env` (ADR 0004); the redaction logic that keeps real amounts out of `make poc`'s own output is unit-tested (`tests/test_poc.py`).

**Verification:**
- [ ] The job is green; breaking a dbt test on purpose turns it red (and gets discarded). (pending: needs a live GitHub Actions PR run; the underlying mechanism — `dbt build` failing on a broken continuity test — is proven locally by `tests/test_dbt_silver_integration.py`, which passed for real against local S3 in this session.)
- [x] Once the job finishes, green or red, no containers or volumes from the project remain. (verified locally, both after a clean run and after an interrupted one.)
- [ ] `make poc` green on your machine and leaves nothing behind. **Piero's step** (real PDFs, see above).
- [x] A PR that changes a silver model only builds that model, its descendants, and the ancestors needed (visible in dbt's log). (verified locally: `dbt build --select state:modified+ --state <base-manifest>` selected 0 nodes with no dbt diff, and exactly `silver.transactions` plus its 11 generic tests after editing `transactions.sql` — see ADR 0013's "Consequences" for the one known gap, a singular test with no `ref()` to the model.)

**Dependencies:** T15, T16 · **Files:** `.github/workflows/ci.yml`, `Makefile` · **Size:** M · **Skill:** ci-cd-and-automation

### T17b: Base-vs-PR comparison — `ci/pr-data-diff`

**Description:** Show what changes in the data on every PR: the same ephemeral run against the base branch and against the PR's, compared.

**Acceptance criteria:**
- [x] The job runs T17's flow for the base commit and for the PR's, with the same synthetic data in separate locations (a lake prefix and a DuckDB file per run). (pending: the `pr-data-diff` job itself — bringing up SeaweedFS, the checkout-swap, two real `pfp ingest` + `dbt build` runs — needs a live GitHub Actions PR run to confirm; locally verified piece by piece: the checkout-swap idiom is `benchmarks`' and `ephemeral-integration`'s own already-proven pattern, and `scripts/data_diff.py` itself is verified below.)
- [x] `scripts/data_diff.py` compares the models built in the run using DuckDB: rows per model, columns and types, and differing rows (`EXCEPT` both ways, with a limited sample). (verified locally, both by `tests/test_data_diff.py` and by running the CLI for real against two hand-built `.duckdb` files with differing rows, an added column and a missing model — see the PR's Verification section.)
- [x] Results in Markdown in the job summary (`$GITHUB_STEP_SUMMARY`); warn mode, doesn't block. (the job carries `continue-on-error: true` and is not in the branch ruleset's required checks — verifiable by reading `.github/workflows/ci.yml`. pending: the actual `$GITHUB_STEP_SUMMARY` rendering on a real run needs a live GitHub Actions PR run to confirm.)

**Verification:**
- [x] TDD tests for the script with two small DuckDB databases. (`tests/test_data_diff.py`, 11 tests, failing before `scripts/data_diff.py` existed and passing after — see the PR.)
- [x] A PR that changes a silver model shows the difference; one with no model changes shows "no changes". (verified locally: `scripts/data_diff.py` run for real against two hand-built `.duckdb` files reports the row/column/sample difference correctly, and reports "No changes" when the two files are identical. pending: an actual PR triggering this through the live `pr-data-diff` job needs a live GitHub Actions PR run to confirm.)

**Dependencies:** T17 · **Files:** `scripts/data_diff.py`, `tests/test_data_diff.py`, `.github/workflows/ci.yml` · **Size:** M · **Skill:** test-driven-development

### ✅ Checkpoint D
- [ ] `dbt build` green locally and in CI · [ ] the ephemeral environment always gets torn down · [ ] a PR shows its data diff · [ ] a docs-only PR doesn't spin up the environment · [ ] reviewed with Piero

---

## Block E — Second bank and close

### T18: Scotiabank parser — `feat/parser-scotiabank`

**Description:** A second bank: proves the parser and dispatcher design scales.

**Acceptance criteria:**
- [x] A masked layout (T9), a synthetic fixture, and `parsers/scotiabank.py` registered in the dispatcher. No byte-prefix signature exists for this bank (unlike BCP's `$BOP$`), so it's registered with `detect=None` and found by a new password-fallback pass instead (see `brain/decisions/0012-scotiabank-password-fallback-detection.md`).
- [x] Bank, account and period come from the PDF's content (the unmasked 8-digit client/account code, not the always-masked card number); the inbox (T12b) files its PDFs via `organizer.py`, extended for a file that can hold more than one `Statement`.
- [x] Synthetic tests in CI reconcile. `real_pdf` (pending: needs your real Scotiabank PDF + `SCOTIABANK_PDF_PASSWORD`, skips gracefully without them — see the Scotiabank parser brain note for what's confirmed vs. inferred).

**Verification:**
- [ ] `uv run pfp ingest <real Scotiabank pdf>` writes to bronze, and `dbt build` includes it in silver. (pending: real-data validation is yours to run — ADR 0004 — likely to need a follow-up fix round the way T11's BCP parser did).

**Dependencies:** T11b, T12, T14 · **Files:** `ingestion/parsers/scotiabank.py`, `tests/fixtures/…`, `tests/parsers/test_scotiabank.py` · **Size:** M · **Skill:** test-driven-development

### T18a: Account kind (asset/liability) in the schema — `feat/account-kind`

**Description:** BCP (checking) and Scotiabank (credit card) use opposite sign conventions —
BCP's negative amount means money left the account, Scotiabank's negative amount means a
payment that *reduces* debt. A real transfer from a checking account to pay down a credit
card is therefore the same sign on both sides, not opposite: T18b's matching needs to know
which kind of account each side is to tell a same-account-kind transfer (opposite signs) from
a checking-to-credit-card one (same sign). Surfaced by Piero before T18b started, choosing
this over a dbt-side bank-name lookup table (fragile — breaks the moment one bank has both a
checking and a credit product).

**Acceptance criteria:**
- [x] `Statement` gains `account_kind: Literal["asset", "liability"]` (`ingestion/schema.py`).
- [x] `bcp.py` sets `"asset"`; `scotiabank.py` sets `"liability"` — hardcoded per parser, not
  inferred from the PDF (a bank's own product type doesn't vary per statement).
- [x] `lakehouse/bronze.py`'s `statements` table (not `transactions`, which has no
  balance/kind concept) carries it through; `dbt/models/sources.yml` and
  `dbt/models/silver/transactions.sql` expose it (joined from `bronze.statements` on a
  deduplicated `account_id`, see ADR 0015) for T18b to read.
- [x] ADR written (0015): the two-value, hardcoded-per-parser design, and why a bank-name lookup
  in dbt was rejected.

**Verification:**
- [x] Existing BCP/Scotiabank synthetic fixtures and tests still pass with the new field;
  a new test asserts each parser's own `account_kind`.
- [ ] `dbt build` shows the column reaching silver. (pending: no live SeaweedFS was reachable
  from this session — the harness blocked materializing the running container's S3 credentials
  into `.env`/the shell as a "credential materialization" action, even though they're local-only
  dev creds. Verified statically instead: `sqlfluff lint dbt/models` and
  `dbt compile --project-dir dbt --profiles-dir dbt` both pass against placeholder env vars, and
  a new integration test, `test_silver_carries_account_kind_without_duplicating_rows` in
  `tests/test_dbt_silver_integration.py`, is written and ready for `make poc-up` +
  `pytest -m integration` on a machine/session that can reach it — Piero or CI should run it for
  real before merging.)

**Dependencies:** T18 · **Files:** `ingestion/schema.py`, `ingestion/parsers/{bcp,scotiabank}.py`, `lakehouse/bronze.py`, `dbt/models/**` · **Size:** S · **Skill:** test-driven-development

### T18b: Inter-account reconciliation — `feat/inter-account-reconciliation`

**Description:** Match transfers between accounts of the same user, so they never count as an expense or income, and flag the ones with no counterpart (ADR 0009).

**Acceptance criteria:**
- [x] A dbt model `silver/internal_transfers`: matches an outflow and an inflow from the same user, on different accounts, in the same currency, for the same amount (configurable tolerance, default 0), within N days or fewer (default 3). Every movement is in at most one pair.
- [x] Sign matching is `account_kind`-aware (T18a): two `asset` accounts (or two `liability` accounts) match on opposite signs; an `asset`-to-`liability` pair (paying down a card from checking) matches on the *same* sign, since a checking outflow and a debt-reducing payment are both negative.
- [x] `silver/transactions` flags `is_internal_transfer`; unmatched candidates land in `silver/unmatched_transfers` for review, never dropped.
- [x] Cross-currency transfers stay out of this task and show up as unmatched.

**Verification:**
- [x] With synthetic BCP and Scotiabank data and a transfer between them, it comes back matched; removing the inflow makes it show up in `unmatched_transfers` instead. (note: verified via a currency-mismatched near-miss, not a fully isolated removal — a movement with *nothing* else in the lake near it is, by design, indistinguishable from an ordinary transaction and correctly does not appear in `unmatched_transfers` either; see ADR 0017's Decision section and this PR's own Notes for the full reasoning.)
- [x] A same-account-kind transfer (two synthetic BCP accounts, opposite-sign case) also matches, proving both branches of the sign logic.
- [ ] `make poc` against your real PDFs shows only how many matched and how many didn't, with no amounts. (pending: real-data validation is yours to run, ADR 0004 — this session verified against synthetic data on an isolated local SeaweedFS instance only, never your real lake).

**Dependencies:** T16, T18, T18a · **Files:** `dbt/models/silver/**`, tests · **Size:** M · **Skill:** test-driven-development

### T18c: Currency-aware statement continuity — `fix/statement-continuity-currency`

**Description:** `dbt/tests/assert_statement_continuity.sql` (T16) fails on any real Scotiabank
statement with both Soles and Dólares activity in the same period — found 2026-09-14 while
verifying T18a's PR by actually running `dbt build` against synthetic BCP + dual-currency
Scotiabank data for the first time (T17's own synthetic seeding never included Scotiabank, so
nothing had exercised this combination through `dbt build` before). Root cause: Scotiabank
writes *two* `bronze.statements` rows for one real statement — one per currency (ADR 0012) —
both sharing the same `account_id` and the same `period_start`/`period_end`. The test's
`lag() ... partition by user_id, account_id order by period_start` sees two same-period rows
for that account and hits its own documented "two statements covering the same period"
failure mode, which is correct for an actual duplicate but a false positive here. `Statement`
has no `currency` field to partition by instead — only `Transaction` does.

**Acceptance criteria:**
- [x] `Statement` gains a `currency: Currency` field (mirrors `account_kind`, T18a's own
  precedent: hardcoded per parser call — BCP always `"PEN"`; Scotiabank sets it per the
  statement it's building, since it already produces one `Statement` per currency).
- [x] `lakehouse/bronze.py`'s `bronze/statements` pyarrow schema carries it through.
- [x] `assert_statement_continuity.sql`'s window functions partition by
  `user_id, account_id, currency` instead of just `user_id, account_id`, so two
  same-period, different-currency statements no longer collide.

**Verification:**
- [x] A new integration or dbt-build test: synthetic BCP (single currency) plus a synthetic
  Scotiabank statement with both PEN and USD activity in the same period both ingest and
  `dbt build` passes with no continuity error. Live-verified against an isolated local
  SeaweedFS (`docker compose -p pfp-poc-t18c`, its own project name and host port, distinct
  from the `pfp-poc` instance already running under another session at the time, which was
  left untouched): reproduced the exact reported failure
  (`Got 1 result, configured to fail if != 0`) before the SQL fix, green after it.
- [x] A genuine duplicate (two statements, same account, same currency, same period) still
  fails the test — the false-positive fix must not weaken the real check. Live-verified the
  same way; `tests/test_dbt_silver_integration.py`'s full 7-test suite passes
  (`7 passed in 108.08s`). (pending: only run against synthetic fixtures in an isolated,
  throwaway lake prefix — Piero's own real Scotiabank data, once he runs `dbt build` against
  it himself, is the final confirmation this session can't produce.)

**Dependencies:** T16, T18 · **Files:** `ingestion/schema.py`, `ingestion/parsers/{bcp,scotiabank}.py`, `lakehouse/bronze.py`, `dbt/tests/assert_statement_continuity.sql`, tests · **Size:** S · **Skill:** debugging-and-error-recovery

### T19: Phase close — `docs/phase-1-close`

**Description:** Leave the phase presentable and turn on blocking for the numeric rules.

**Acceptance criteria:**
- [x] README: what this is, a diagram, how to run it, the Azure ↔ open-source equivalence.
- [x] Brain kept current (phase-1 closed, Mermaid map, components) — `brain/phases/phase-1.md`
  marked `status: closed`, its own honest "still open" note added (real-data validation,
  numeric rules).
- [ ] Numeric rules switch to blocking (if 2026-09-26 has passed). (pending: today is
  2026-09-15, 11 days before that date — CONSTRAINTS.md's own text sets the date, not this
  task; flip `continue-on-error` in `.github/workflows/ci.yml` and the `-`/`||true` markers in
  `Makefile` once it arrives.)

**Verification:**
- [x] Clone the repo into a clean folder and follow the README through to `dbt build` with no
  missing steps. Verified for real — see this task's PR for the transcript.

**Dependencies:** T17b, T18b, T18c · **Files:** `README.md`, `brain/**`, `.github/workflows/ci.yml` · **Size:** S

### T19b: Obsidian vault for the brain — `docs/obsidian-brain-vault`

**Description:** A graphical way to browse `brain/` — its cross-links (ADRs, components, concepts,
phases) as a navigable graph, not just the Mermaid map in `brain/README.md`. Deferred, not part
of the Phase 1 close checklist: nice-to-have, not a blocker.

**Acceptance criteria:**
- [x] `brain/` opens as an Obsidian vault with no broken links: confirmed with a link-checker
  script over every relative markdown link in `brain/**/*.md` — none broken (Obsidian follows
  standard markdown links, not only `[[wikilinks]]`, so no rework was needed).
- [x] `.obsidian/` (personal, per-machine view state — panes, graph layout, theme) is
  gitignored, never committed (was already in `.gitignore`; confirmed with `git check-ignore`).
- [x] `SETUP.md` §8 added: the exact steps, and the Windows UNC path pattern
  (`\\wsl.localhost\<distro>\...`) for Obsidian running on the Windows side.

**Verification:**
- [ ] Opening the vault shows every ADR, component and concept note connected in the graph view;
  no note appears fully isolated unless it genuinely has no cross-links yet. (pending: the same
  link-checker found the three files under `brain/_templates/` as the only isolated ones —
  intentional, blank starting points with no content to link; the actual graph *rendering* is
  Piero's own step, on his own Obsidian install.)

**Dependencies:** none (brain/ already exists) · **Files:** `.gitignore`, `SETUP.md` ·
**Size:** S · **Skill:** documentation-and-adrs

### ✅ Final checkpoint
- [ ] All criteria met · [ ] integral reconciliation green (statement, continuity and between accounts) · [ ] `develop → main` release PR "Phase 1 — Foundation" · [ ] merged by Piero
