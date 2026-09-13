---
type: phase
phase: 1
---

# Phase 1 — Foundation

A bank statement PDF (BCP or Scotiabank) gets parsed, reconciled, skipped if already ingested,
and written to bronze; dbt builds silver with tests, and CI validates every PR. Full plan in
[tasks/plan.md](../../tasks/plan.md) and tasks in [tasks/todo.md](../../tasks/todo.md).

## Status

| Block | Tasks | Status |
|---|---|---|
| A — Repo foundation | T1 guards (#8) · T2 Python project (#10) · T3a brain (#14) · T3b CLAUDE.md (#15) · T4 CONSTRAINTS (#17, fixes in #21) · T5 CI quality gates (#26) | T1–T5 done |
| B — Ingestion | T6–T12b | T6 schema (#30, fix #32) · T7 file hash (#28) · T8 reconciliation (#34) · T9 inspector (#16) · T10 synthetic fixture (#29) · T11 BCP parser · T12 dispatcher/CLI · T11b OCR fallback (#38) · T12b inbox organizer (#39): all done |
| C — Lakehouse | T13–T15 | T13 local S3 (SeaweedFS) · T14 bronze writer · T14c bronze backfill · T15 benchmarks + impact-based CI: all done |
| D — Transformation | T16, T17, T17b | Pending |
| E — Second bank and close | T18, T18b, T19 | Pending |

Also integrated: [SETUP.md](../../SETUP.md) with environment setup (#10), the ephemeral
environments and impact-based CI plan (#12), [CLAUDE.md](../../CLAUDE.md) with the rules for
agents, the PR template and PROJECT.md kept current (#15), and the multi-user, multi-account,
integral reconciliation plan (#19).

## Components

- [Security guards](../components/security-guards.md) — built (T1).
- [Python project](../components/python-project.md) — built (T2).
- [CI](../components/ci.md) — in progress: branch policy and quality gates (T5), impact-based
  `changes` and `benchmarks` jobs (T15) done; ephemeral environment in T17.
- [Masked layout inspector](../components/layout-inspector.md) — built (T9).
- [Quality bar](../components/quality-bar.md) — built (T4).
- [BCP parser](../components/bcp-parser.md) — built (T11), provisional column layout pending a real masked dump.
- [Dispatcher and CLI](../components/cli.md) — built (T12, T12b, T14, T14c): `pfp parse`, `pfp organize`, `pfp ingest`, `pfp backfill`; one bank registered so far.
- [Inbox organizer](../components/inbox-organizer.md) — built (T12b).
- [Lakehouse](../components/lakehouse.md) — built (T14, T14c): bronze in Delta, partitioned by `user_id`, with a backfill that replaces a file's rows.

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

## Concepts

- [Medallion architecture](../concepts/medallion.md)
- [Idempotency](../concepts/idempotency.md)
- [Business key](../concepts/business-key.md)
- [Reconciliation](../concepts/reconciliation.md)
- [File-level dedup](../concepts/file-level-dedup.md)
- [Users and accounts](../concepts/users-and-accounts.md)
