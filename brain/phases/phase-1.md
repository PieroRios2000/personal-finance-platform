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
| B — Ingestion | T6–T12b | T9 inspector done (#16); T10 synthetic fixture done (#29); T12b (inbox) planned (#19); the rest pending |
| C — Lakehouse | T13–T15 | Pending |
| D — Transformation | T16, T17, T17b | Pending |
| E — Second bank and close | T18, T18b, T19 | Pending |

Also integrated: [SETUP.md](../../SETUP.md) with environment setup (#10), the ephemeral
environments and impact-based CI plan (#12), [CLAUDE.md](../../CLAUDE.md) with the rules for
agents, the PR template and PROJECT.md kept current (#15), and the multi-user, multi-account,
integral reconciliation plan (#19).

## Components

- [Security guards](../components/security-guards.md) — built (T1).
- [Python project](../components/python-project.md) — built (T2).
- [CI](../components/ci.md) — in progress: branch policy and quality gates (T5) done; impact-based CI in T15.
- [Masked layout inspector](../components/layout-inspector.md) — built (T9).
- [Quality bar](../components/quality-bar.md) — built (T4).

## Decisions

| ADR | Decision | Note |
|---|---|---|
| 0001 | Python 3.12 with uv | [ADR 0001](../decisions/0001-python-312-with-uv.md) |
| 0002 | DuckDB + delta-rs before Spark | [ADR 0002](../decisions/0002-duckdb-and-delta-rs-before-spark.md) |
| 0003 | Local S3 with SeaweedFS | [ADR 0003](../decisions/0003-local-s3-with-seaweedfs.md) |
| 0004 | Real PDFs never leave your machine | [ADR 0004](../decisions/0004-real-pdfs-never-leave-your-machine.md) |
| 0005 | `Transaction` with `Decimal`, user and HMAC-based account + last 4 | Written in T6 |
| 0006 | Lake location by URI | Written in T14 |
| 0007 | Ephemeral per-PR environments | [ADR 0007](../decisions/0007-ephemeral-per-pr-environments.md) |
| 0008 | Impact-based CI | Written in T15 |
| 0009 | Several users and accounts; PDF content rules over the file name | Written in T6 |

## Concepts

- [Medallion architecture](../concepts/medallion.md)
- [Idempotency](../concepts/idempotency.md)
- [Business key](../concepts/business-key.md)
- [Reconciliation](../concepts/reconciliation.md)
- [File-level dedup](../concepts/file-level-dedup.md)
- [Users and accounts](../concepts/users-and-accounts.md)
