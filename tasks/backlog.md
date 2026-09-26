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
- [ ] Numeric CI rules leave warn-mode on 2026-09-26 (two-line change).

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

- [ ] **A public URL** (T42): Superset, Dex and `dex-register` reachable from the internet through
      a Cloudflare Tunnel (the opt-in `docker-compose.override.yml.dist` from T40 already attaches
      the network). Needs the owner's domain and, in this repo, the public hostnames wherever
      `localhost` is hard-coded today (Dex's `redirectURIs` and the browser-facing `DEX_ISSUER`,
      Superset behind an HTTPS proxy). Cost: the tunnel and Zero Trust (up to 50 users) are free;
      only a domain costs (about USD 10-11 a year, no metered billing), so the spend cap is
      "do not upgrade the plan" and "turn auto-renew off".
- [ ] **Login page links and password reset** (T43): "Create account" and "Forgot password" on Dex's
      login page (Dex lets its web templates be customized). Reset by a **single-use random token
      with an expiry** (only its hash stored), emailed over the SMTP the alerting already configures
      (Phase 7), handled by `dex-register` (`/forgot`, `/reset?token=`) and applied over gRPC
      `UpdatePassword`. It must answer the same whether the email exists or not, and rate-limit.
      Depends on T42 (the link must open from outside) and on SMTP. **Open:** accounts added with
      `make dex-add-user` are *static* (read-only over gRPC, found out re-scoping the owner's own
      account) and cannot be reset this way: migrate them to dynamic storage first.
- [ ] **The upload portal** ([Phase 5](../PROJECT.md)): upload -> `inbox/<user_id>/` -> pipeline.
      Sections by **file type** (statement PDFs, card balance, manual Excel: savings and
      investments), not by bank: bank and account are detected from the content
      ([ADR 0009](../brain/decisions/0009-multi-user-multi-account-content-over-filename.md)) and
      archived under `raw/<user>/<bank>/<account>/`; what the user picks is only a hint, and a
      mismatch goes to `_needs_review`. Decide first (each needs an ADR):
      - the destination `user_id` comes from the signed-in session, never a form field;
      - how a new account gets a safe `user_id` and is bound to it (today it sees no data until
        the operator runs `make dex-add-user --username`);
      - PDF passwords: one per bank in `.env` today; several people need one each, and storing
        other people's passwords is a security decision;
      - privacy: [ADR 0004](../brain/decisions/0004-real-pdfs-never-leave-your-machine.md) covers
        the owner's own statements, not receiving other people's.
- [ ] **"Upload your files" button in Superset**, last, once the portal exists: a Handlebars chart
      that renders the message and the link only when its query returns 0 rows (which is what a
      row-level-filtered new account gets).

## Next phases (planned, nothing built)

- [x] [Phase 7 — Alerting](../brain/phases/phase-7.md): built. Left: Dagster-triggered alerts.
- [ ] [Phase 6 — Savings-goal projection](../brain/phases/phase-6.md): the manual-Excel
      importer: Ripley savings and investment tracking (`Inversiones` sheet, monthly returns) **done**, then the cash-flow projection and its own sol/dólar exchange-rate section (the only
      place currencies are converted). Scope in [ADR 0025](../brain/decisions/0025-savings-goal-projection-counts-liquid-savings-only.md).
- [ ] **Phase 2 extension, T26-T33: PostgreSQL as dbt's store, then Superset** (decided 2026-09-19,
      [ADR 0029](../brain/decisions/0029-dbt-stores-silver-and-gold-in-postgres.md)). Order and
      acceptance criteria in [`todo-phase2.md`](todo-phase2.md). Then the owner tries the data
      visualization, the dbt catalog and the architecture before Phase 3 (ML).
- [ ] Phase 3 (ML), 4 (cloud), 5 (uploader): see [PROJECT.md](../PROJECT.md).
