---
type: phase
phase: 1
status: closed
---

# Phase 1 — Foundation (closed)

A bank statement PDF (BCP or Scotiabank) gets parsed, reconciled, skipped if already ingested,
and written to bronze; dbt builds silver with tests, and CI validates every PR. Full plan in
[tasks/plan.md](../../tasks/plan.md) and tasks in [tasks/todo.md](../../tasks/todo.md).

## Status

| Block | Tasks | Status |
|---|---|---|
| A — Repo foundation | T1 guards (#8) · T2 Python project (#10) · T3a brain (#14) · T3b CLAUDE.md (#15) · T4 CONSTRAINTS (#17, fixes in #21) · T5 CI quality gates (#26) | T1–T5 done |
| B — Ingestion | T6–T12b | T6 schema (#30, fix #32) · T7 file hash (#28) · T8 reconciliation (#34) · T9 inspector (#16) · T10 synthetic fixture (#29) · T11 BCP parser · T12 dispatcher/CLI · T11b OCR fallback (#38) · T12b inbox organizer (#39): all done |
| C — Lakehouse | T13–T15 | T13 local S3 (SeaweedFS) · T14 bronze writer · T14c bronze backfill · T15 benchmarks + impact-based CI: all done |
| D — Transformation | T16, T17, T17b | T16 dbt silver done; T17 ephemeral integration environment done; T17b base-vs-PR data diff done |
| E — Second bank and close | T18, T18a, T18b, T18c, T19 | T18 Scotiabank parser: built, pending real-data validation · T18a account_kind: built · T18c currency-aware continuity: built · T18b internal-transfer reconciliation: built · T19 phase close: done |

Also integrated: [SETUP.md](../../SETUP.md) with environment setup (#10), the ephemeral
environments and impact-based CI plan (#12), [CLAUDE.md](../../CLAUDE.md) with the rules for
agents, the PR template and PROJECT.md kept current (#15), and the multi-user, multi-account,
integral reconciliation plan (#19). Local visualization: `dbt/pfp.duckdb` (T16's own build
artifact) opens directly in DBeaver, silver with zero setup and bronze with a one-time DuckDB
persistent-secret-and-views setup — [SETUP.md §7](../../SETUP.md#7-browsing-the-lake-in-dbeaver),
[dbt silver](../components/dbt-silver.md). T19b (brain in Obsidian): confirmed with a
link-checker that every relative link in `brain/**/*.md` resolves and nothing is unexpectedly
isolated — steps in [SETUP.md §8](../../SETUP.md#8-browsing-the-brain-in-obsidian).

**Closing this phase (T19, 2026-09-15).** Every task is built, tested (synthetic data) and
merged. Two things are still honestly open, not glossed over:

- **Real-data validation is Piero's own step** (ADR 0004): the Scotiabank parser, the
  currency-aware continuity fix and inter-account matching have never run against his actual
  statements — only synthetic fixtures and, for the pipeline itself, his own real BCP data via
  `pfp backfill`. `make poc` is how he confirms the rest, whenever he's ready.
- **The numeric rules (coverage, security, performance, architecture) are still in warn mode**
  — CONSTRAINTS.md's own switch date is 2026-09-26, which hadn't passed as of this close.
  Flipping `continue-on-error` off in `.github/workflows/ci.yml` and the `-`/`||true` markers
  in the `Makefile` is a two-line change once that date arrives; deliberately not done early,
  since CONSTRAINTS.md's own text is what sets the date, not this note.

## Components

- [Security guards](../components/security-guards.md) — built (T1).
- [Python project](../components/python-project.md) — built (T2).
- [CI](../components/ci.md) — in progress: branch policy and quality gates (T5), impact-based
  `changes` and `benchmarks` jobs (T15), the `ephemeral-integration` job plus `make poc` (T17),
  and the `pr-data-diff` job plus `scripts/data_diff.py` (T17b) all done; every job's own
  wiring still needs a live GitHub Actions PR run to fully confirm.
- [Masked layout inspector](../components/layout-inspector.md) — built (T9).
- [Quality bar](../components/quality-bar.md) — built (T4).
- [BCP parser](../components/bcp-parser.md) — built (T11), provisional column layout pending a real masked dump.
- [Dispatcher and CLI](../components/cli.md) — built (T12, T12b, T14, T14c, T18): `pfp parse`, `pfp organize`, `pfp ingest`, `pfp backfill`; two banks registered, BCP and Scotiabank.
- [Inbox organizer](../components/inbox-organizer.md) — built (T12b).
- [Lakehouse](../components/lakehouse.md) — built (T14, T14c): bronze in Delta, partitioned by `user_id`, with a backfill that replaces a file's rows.
- [dbt silver](../components/dbt-silver.md) — built (T16): bronze read through `delta_scan()`, `silver.transactions`, and continuity reconciliation across statement periods.
- [Scotiabank parser](../components/scotiabank-parser.md) — built (T18): credit-card statement, one `Statement` per currency, found by the dispatcher's password-fallback pass; pending real-data validation.
- [BCP parser](../components/bcp-parser.md) and [Scotiabank parser](../components/scotiabank-parser.md), [Lakehouse](../components/lakehouse.md) and [dbt silver](../components/dbt-silver.md) — extended (T18a): `account_kind` (`asset`/`liability`) on `Statement`, hardcoded per parser, carried through bronze and joined into `silver.transactions` for T18b.
- [BCP parser](../components/bcp-parser.md), [Scotiabank parser](../components/scotiabank-parser.md), [Lakehouse](../components/lakehouse.md) and [dbt silver](../components/dbt-silver.md) — extended (T18c): `currency` on `Statement`, hardcoded per parser, carried through bronze; the continuity test partitions by it too, fixing a false positive found running `dbt build` against dual-currency Scotiabank data for the first time.
- [dbt silver](../components/dbt-silver.md) — extended (T18b): `silver.internal_transfer_matches`, `silver.internal_transfers` and `silver.unmatched_transfers`, plus an `is_internal_transfer` flag joined into `silver.transactions` — an account_kind-aware, mutual-nearest-neighbor match between two accounts of the same user, with cross-currency and unpaired candidates surfaced for review instead of dropped.

## Decisions

| ADR | Decision | Note |
|---|---|---|
| 0001 | Python 3.12 with uv | [ADR 0001](../decisions/0001-python-312-with-uv.md) |
| 0002 | DuckDB + delta-rs before Spark | [ADR 0002](../decisions/0002-duckdb-and-delta-rs-before-spark.md) |
| 0003 | Local S3 with SeaweedFS | [ADR 0003](../decisions/0003-local-s3-with-seaweedfs.md) |
| 0004 | Real PDFs never leave your machine | [ADR 0004](../decisions/0004-real-pdfs-never-leave-your-machine.md) |
| 0005 | `Transaction` with `Decimal`, user and HMAC-based account + last 4 | Written in T6 |
| 0006 | Lake location by URI | [ADR 0006](../decisions/0006-lake-location-by-uri.md) |
| 0007 | Ephemeral per-PR environments | [ADR 0007](../decisions/0007-ephemeral-per-pr-environments.md) |
| 0008 | Impact-based CI | [ADR 0008](../decisions/0008-impact-based-ci.md) |
| 0009 | Several users and accounts; PDF content rules over the file name | Written in T6 |
| 0010 | A bronze backfill replaces a file's rows, it doesn't version them | [ADR 0010](../decisions/0010-bronze-backfill-replaces-not-versions.md) |
| 0011 | `delta_scan()` as a dbt source, on an on-disk DuckDB | [ADR 0011](../decisions/0011-delta-scan-as-a-dbt-source.md) |
| 0012 | Scotiabank found by password fallback; `parse()` returns `list[Statement]` project-wide | [ADR 0012](../decisions/0012-scotiabank-password-fallback-detection.md) |
| 0013 | dbt state comparison via a base-ref worktree | [ADR 0013](../decisions/0013-dbt-state-comparison-via-a-base-ref-worktree.md) |
| 0014 | pr-data-diff: shared instance by URI prefix, always a full build | [ADR 0014](../decisions/0014-pr-data-diff-shared-instance-full-build.md) |
| 0015 | `account_kind` (asset/liability) on `Statement`, joined into silver | [ADR 0015](../decisions/0015-account-kind-asset-or-liability.md) |
| 0016 | `currency` on `Statement`; continuity test partitioned by currency too | [ADR 0016](../decisions/0016-currency-aware-statement-continuity.md) |
| 0017 | Internal-transfer matching: mutual nearest neighbor, currency-relaxed candidacy | [ADR 0017](../decisions/0017-internal-transfer-matching-mutual-nearest-neighbor.md) |

## Concepts

- [Medallion architecture](../concepts/medallion.md)
- [Idempotency](../concepts/idempotency.md)
- [Business key](../concepts/business-key.md)
- [Reconciliation](../concepts/reconciliation.md)
- [File-level dedup](../concepts/file-level-dedup.md)
- [Users and accounts](../concepts/users-and-accounts.md)
