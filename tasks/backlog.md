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

## Next phases (planned, nothing built)

- [x] [Phase 7 — Alerting](../brain/phases/phase-7.md): built. Left: Dagster-triggered alerts.
- [ ] [Phase 6 — Savings-goal projection](../brain/phases/phase-6.md): first the manual-Excel
      importer (Ripley savings + investment tracking; template done, waiting for the owner's masked
      dump), then the cash-flow projection and its own sol/dólar exchange-rate section (the only
      place currencies are converted). Scope in [ADR 0025](../brain/decisions/0025-savings-goal-projection-counts-liquid-savings-only.md).
- [ ] Phase 3 (ML), 4 (cloud), 5 (dashboard): see [PROJECT.md](../PROJECT.md).
