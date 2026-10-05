# Backlog (what is next, in order)

Not a plan: a list so nothing agreed in conversation is lost. Each item becomes its own
branch and PR when it is picked up; see [`CLAUDE.md`](../CLAUDE.md) for how.

## Found on the first real run (2026-09)

- [x] `scripts/poc.py`: `_safe_dbt_lines` showed no dbt lines on real output (timestamp prefix and
      ANSI colours). Fixed with Phase 7.
- [ ] Inbox organizer only reads `inbox/<user>/*.pdf`; PDFs pasted in nested folders are ignored
      silently. Either read subfolders or say so in the report.
- [ ] Decide whether a failing continuity test should skip every downstream node (today one
      failing source test skipped 93 of 127 nodes, silver and gold included).
- [x] Numeric CI rules leave warn-mode on 2026-09-26 (T19): the `-` and `continue-on-error` came off for coverage, pip-audit, bandit and import-linter.
- [ ] Benchmark comparison: still warns (a single outlier made the mean 50% worse on identical code). Decide: gate on the median (`--benchmark-compare-fail=median:20%`) instead of the mean, then it can block.

## CI parity (done 2026-09-19)

- [x] `make ci-local` / `make ci-local-full`: CI's own jobs, from `ci.yml`, in a clean clone with only
      each job's environment (SETUP.md, `brain/components/ci.md`); part of the Definition of Done.

## CI speed (evaluation point, raised 2026-09-19)

The ephemeral environment (`ephemeral-integration`) now takes about 20 minutes per PR that touches
`dbt/`, `ingestion/` or `lakehouse/`, so it hit its old 20-minute limit and was cancelled
(#82; limit raised to 30). Where the time goes, measured on that run:

| Step | Time |
|---|---|
| `pytest -m integration` (39 tests, each a real `dbt build`, ~26 s each) | **17.1 min** |
| Dagster end-to-end, both passes | 1.8 min |
| Environment up/down, sqlfluff, Elementary steps | ~1.2 min |

So the end-to-end flow is *not* the cost (under 2 minutes); the cost is the 39 integration tests,
and **all 39 run whatever the PR changed**: the impact map (ADR 0008) decides whether the job runs,
not which tests inside it. Options, in the order they are worth doing:

- [ ] **Run only the impacted integration test files.** Checked while doing the parallel work:
      it saves less than it looks, because every test's `dbt build` runs *every* dbt test, so
      almost any `dbt/` change touches all of them; it only helps for gold-only, test-only or
      script-only changes. Worth doing after making each build cheaper. Map changed paths to test files (a gold
      model → `test_dbt_gold_integration.py`; `ingestion/` or `lakehouse/` → bronze and Dagster
      tests; silver models or shared macros → silver, incremental merge, transfers), in
      `scripts/ci_impact.py` next to the existing map. Same safety net as ADR 0008: pushes to
      `develop` and the weekly run still run all of them, so a missed dependency is caught there.
- [x] **Run the tests in parallel** (`pytest-xdist -n 4`, one test lake per worker). Locally the
      whole integration suite went from about 33 min one after another to 12.9 min on 4 workers
      (6 CPUs, all passing); CI's own number is in the PR that introduced it.
- [ ] **Make each test's `dbt build` cheaper.** Most tests need one model or one test, not all
      124 nodes plus Elementary's hooks: use `--select` and skip Elementary where it is not the
      subject.
- [ ] **Show the cost on every PR:** print `--durations` for the integration run in the job
      summary and keep a target (proposed: a PR that touches one layer gets its CI result in
      under 10 minutes), so slowdowns are seen when they are introduced, not when the job is
      cancelled.
- [ ] Skip the second Dagster idempotency pass unless `ingestion/` or `lakehouse/` changed
      (about 0.7 min; small, last).

## Identity, public access and the upload portal (raised 2026-09-26)

Built so far on the Dex line: login by email (T39, ADR 0034), self-service sign-up with an
invite code (T40, ADR 0035), row-level data by `user_id` (T41, ADR 0036). What is left, in the
order agreed:

- [x] **A public URL** (T42, ADR 0037; live and tested by the owner): Superset,
      Dex and `dex-register` reachable from the internet through a Cloudflare Tunnel whose
      `cloudflared` connector runs inside the stack. Needs the owner's domain and, in this repo, the public hostnames wherever
      `localhost` is hard-coded today (Dex's `redirectURIs` and the browser-facing `DEX_ISSUER`,
      Superset behind an HTTPS proxy). Cost: the tunnel and Zero Trust (up to 50 users) are free;
      only a domain costs (about USD 10-11 a year, no metered billing), so the spend cap is
      "do not upgrade the plan" and "turn auto-renew off".
- [x] **Login page links and password reset** (T43, ADR 0038; built, needs the owner's SMTP to send real mail): "Create account" and "Forgot password" on Dex's
      login page (Dex lets its web templates be customized). Reset by a **single-use random token
      with an expiry** (only its hash stored), emailed over the SMTP the alerting already configures
      (Phase 7), handled by `dex-register` (`/forgot`, `/reset?token=`) and applied over gRPC
      `UpdatePassword`. It must answer the same whether the email exists or not, and rate-limit.
      Depends on T42 (the link must open from outside) and on SMTP. Static accounts, which cannot be reset,
      are gone: every account is dynamic (ADR 0039).
- [x] **The upload portal** ([Phase 5](../PROJECT.md), ADR 0040/0041): upload -> `inbox/<user_id>/`
      -> pipeline, built end to end: bank statements by kind, bank and currency (T44, T46), the
      Excel section for savings and investments (T49), requests of up to 10 files accepted or
      rejected whole (T48), a review-alert email to the owner (T47), the dashboard link (T45). The
      four decisions raised here are resolved: the destination `user_id` comes from the signed-in
      session, never a form field; a new account gets a safe `user_id` automatically
      (`portal.new_user_id`), no operator step; the PDF password is typed per upload and never
      stored; privacy is covered by keeping the public URL on fictional data only (ADR 0042) --
      real statements, the owner's or anyone else's, stay off the internet-facing instance. Left:
      a distinct "card balance" file type was never built (folded into the bullet below, since it
      is the same "not read yet, its own request" path as any other unsupported bank or kind).
- [x] **Requests up to 10 files, accepted or rejected whole, sender emailed** (T48, ADR 0041).
- [x] **The portal's Excel section for savings and investments** (T49, ADR 0041 amendment): generic template, structure checked at upload, every row read by the owner's import with the account key, whole workbook accepted or rejected, sender emailed.
- [ ] **Extraction for new banks, kinds and currencies** (T46 keeps the files apart; each one is its own request):
      whatever `make review-uploads` lists that no parser reads (another bank, BCP's credit card, a currency
      other than soles and dollars),
      studied one at a time from a masked layout sample ([layout inspector](../brain/components/layout-inspector.md),
      ADR 0004): a parser, its synthetic fixture, and adding its pair to `SUPPORTED` in
      `upload/portal.py`. Nothing waiting yet.
- [x] **"Upload your files" button in Superset** (T45): the first row of the dashboard. A
      Handlebars chart counts the movements the account may see (row-level security): 0 shows a
      "No data yet" message and a button to the portal, otherwise a slim "Have more statements?"
      link. (A chart cannot be empty in Superset, hence the count and the constant `upload_url()`.)

## Phase 3 — ML in production (started 2026-09-27)

The identity/portal line (T39-T50) is frozen: built, documented, verified; no more effort there
unless something breaks. Phase 3 starts with categorization, per the owner's decision.

- [x] **Category labeling infrastructure** (T51, ADR 0043): the cold-start guesser, the labeling
      file (export/import), `gold.dim_category`, `gold.rpt_movements.category`. Run on the owner's
      real labels since 2026-10-03 (589 descriptions).
- [x] **A trained classifier** (T52, ADR 0044): TF-IDF character n-grams + logistic regression,
      scored (macro-F1, precision per category) against the rules-based baseline on every run
      (`make train-category-model`). Trained on the owner's real labels (589, 10 categories): macro-F1 0.49 on the 543
      reviewed ones, 0.23 for the rules (ADR 0044, amendment of 2026-10-04).
- [x] **Wire the trained model into the labeling file's suggestion** (T53): `export_category_labels.py`
      proposes from the trained model once one has been saved
      (`make train-category-model`), the rules-based guesser until then -- still reviewed, never
      assigned outright. The owner still needs to label enough of his own real descriptions and
      train on them before this actually changes what he sees.
- [x] **Categorize new movements as a batch step** (T54, ADR 0045; reviewer feedback,
      2026-09-27): `pfp ingest`/`make ingest` and the Dagster `bronze` asset now both
      batch-predict a category for every new, unconfirmed movement automatically
      (`scripts.categorize_new_movements`), writing a proposal into
      `gold.rpt_movements` (`category_confirmed = false`), never a live request.
      `make ingest-uploads` (the upload-portal path) reaches it through `pfp ingest` (ADR 0047
      corrected an earlier note saying it did not); `pfp backfill` now calls it too, and the saved
      model proposes only for the user it was trained for. **A FastAPI endpoint is optional**,
      only if a real caller ever needs one (e.g. the upload portal previewing a category
      before the owner processes a request) -- not built speculatively ahead of that.
- [x] **Drift monitoring** (T55, ADR 0046): `make monitor-category-drift` runs Evidently's data drift
      preset on derived features (never the description) of the last 90 days against the older
      movements and writes an HTML report under `~/finance-data/reports/`. Manual, not scheduled;
      no model-confidence column exists to monitor (ADR 0045). A flag at these window sizes is a
      prompt, not a verdict.
- [ ] **Spend forecast per category + savings-goal projection** (specified 2026-10-04,
      [spec](../docs/specs/category-forecast-and-savings-goal.md),
      [ADR 0048](../brain/decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md);
      closes Phase 3's forecasting item and Phase 6's cash-flow projection). Each its own PR, in order:
  - [x] **T56** `forecasting/` skeleton, fixed-expense detection, `make export-plan` (workbook with `Instrucciones`, `Gastos fijos`, `Meta` incl. `usd_to_pen` and the emergency settings; `~/finance-data/plan/`).
  - [x] **T57** `make import-plan` (validates the dollar goal, rate and emergency fields), bronze/silver plan tables, gold `rpt_fixed_expenses`.
  - [x] **T58** forecast core: series, five candidates + baseline, rolling-origin backtest, intervals.
  - [x] **T59** `make forecast`: bronze outputs, MLflow, gold forecast, variance and quality tables.
  - [x] **T60** projection in dollars: buckets, calculated emergency target, two goal lines (`liquid`, `with_risk`), three scenarios, time to goal, adjust view, gold tables.
  - [x] **T61** Superset "Forecast & goal" section with row-level security, demo seed.
  - [x] **T62** realized-vs-backtest monitor, monthly routine and where-to-look updates.
  - [x] **T64** forecast 36 months ahead (intervals only where the backtest measures them, `has_interval`), `rpt_forecast_realized.source` (`backtest` until a second run).
  - [x] **T65** dynamic goal from Superset: `goal_cashflow`/`goal_balances` pieces, virtual dataset `goal_dynamic` and four typed native filters (goal, exchange rate, emergency months, horizon), row-level security on it.
  - [ ] **T63** (follow-up) experiment: recurrence and the fixed/variable mark as classifier features, ADR 0044's protocol and an acceptance margin over the fold spread; a null result is valid (spec section 4.8).
- [ ] **The deferred cost study**: an LLM (Claude) as a per-transaction classifier vs. the trained
      model -- macro-F1 and per-category precision (not just accuracy), latency, cost per
      transaction, cost per month at this project's real volume, against the same held-out labels.
      A concrete MLOps tradeoff narrative, buildable now that T52 exists to compare against.

## Later, if a real business (out of scope for the portfolio, ADR 0042)

- [ ] A privacy policy, consent flow and breach-handling process before any real stranger's real
      financial data may be accepted -- required by Ley 29733 once `prod`'s portal takes a real
      upload, which the current banner does not prevent.
- [ ] A technical control against a real-looking upload on the demo environment (today: notice only).

## Next phases (planned, nothing built)

- [x] [Phase 7 — Alerting](../brain/phases/phase-7.md): built. Left: Dagster-triggered alerts.
- [ ] [Phase 6 — Savings-goal projection](../brain/phases/phase-6.md): the manual-Excel
      importer: Ripley savings and investment tracking (`Inversiones` sheet, monthly returns) **done**, then the cash-flow projection (specified, T56-T62 under Phase 3 above) and its own sol/dólar exchange-rate section (the only
      place currencies are converted). Scope in [ADR 0025](../brain/decisions/0025-savings-goal-projection-counts-liquid-savings-only.md).
- [ ] **Phase 2 extension, T26-T33: PostgreSQL as dbt's store, then Superset** (decided 2026-09-19,
      [ADR 0029](../brain/decisions/0029-dbt-stores-silver-and-gold-in-postgres.md)). Order and
      acceptance criteria in [`todo-phase2.md`](todo-phase2.md). Then the owner tries the data
      visualization, the dbt catalog and the architecture before Phase 3 (ML).
- [ ] Phase 3 (ML), 4 (cloud), 5 (uploader): see [PROJECT.md](../PROJECT.md).
