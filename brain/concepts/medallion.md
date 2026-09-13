---
type: concept
phase: 1
---

# Medallion architecture

Organize the lake into layers of increasing quality, where each layer is built only from the
one before it. That way, a bug is fixed by reprocessing from the layer below, without ever
reading the PDFs again.

| Layer | What it holds in this project | Who writes it | Phase |
|---|---|---|---|
| **Bronze** | Transactions exactly as the parser produces them, plus the ingested-files registry. Append-only | `lakehouse/` with delta-rs | 1 |
| **Silver** | Clean transactions: types, normalized description, currency and account, no duplicates | dbt | 1 (dedup via MERGE in 2) |
| **Gold** | Star schema for analysis: `fact_transactions` + dimensions | dbt | 2 |

## How it applies here

Bronze keeps the "raw but validated" version: it only receives statements that passed
[reconciliation](reconciliation.md). If a normalization rule changes tomorrow, silver rebuilds
from bronze without touching the PDFs, which never leave your machine anyway.

## Related

- [Idempotency](idempotency.md) — reprocessing a layer must not duplicate data.
- [Business key](business-key.md) — how silver recognizes the same transaction across two PDFs.
- [ADR 0002: DuckDB + delta-rs](../decisions/0002-duckdb-and-delta-rs-before-spark.md) — the Delta format behind the layers.
- [ADR 0004: Real PDFs](../decisions/0004-real-pdfs-never-leave-your-machine.md) — why the original PDF is never re-read.
- [Phase 1](../phases/phase-1.md)
