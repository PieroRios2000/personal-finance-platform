# Personal Finance Data Platform

A local, zero-cost data platform that turns real bank statement PDFs into a governed,
reconciled lakehouse — built to demonstrate Data Engineering / Data Lead practice end to end:
ingestion, schema validation, medallion modeling, CI/CD, and architectural documentation, on
100% open-source tooling.

[![CI](https://github.com/PieroRios2000/personal-finance-platform/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/PieroRios2000/personal-finance-platform/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![status](https://img.shields.io/badge/phase%201-foundation-brightgreen)

## What this is

Bank statements (BCP, Scotiabank) come in as password-protected PDFs — some digital, some
scanned. This platform parses them, reconciles every number the PDF itself declares, and
lands them in a bronze → silver Delta Lake, all runnable locally with `docker compose` and
zero cloud spend. It's the same shape of problem a corporate data platform solves, scaled down
to one person's real financial data, with the same engineering discipline:

| In production, this would be... | Here, it's... |
|---|---|
| Azure Data Factory / ADLS | A Python ingestion CLI + SeaweedFS (S3-compatible) |
| Delta/Parquet in the lake | Delta Lake, written with `delta-rs` |
| Synapse / Databricks | DuckDB, embedded — no JVM, no cluster |
| A modeling layer (dbt on Databricks) | dbt-duckdb, reading Delta straight off S3 |
| A CI/CD quality gate | GitHub Actions: lint, types, tests, security, architecture contracts, impact-based performance benchmarks |

## Architecture

```mermaid
flowchart LR
    PDF[("Bank statement PDF\n(BCP · Scotiabank)")] --> CLI["pfp CLI\ndetect → parse → reconcile"]
    CLI --> ARC[("Per-user archive\ncontent-addressed, never overwritten")]
    ARC --> BRZ[("Bronze\nDelta Lake on S3, append-only")]
    BRZ --> SLV[("Silver\ndbt: typed, deduplicated, cross-statement reconciled")]
    BRZ -.backfill.-> BRZ

    style PDF fill:#f5deb3,stroke:#8b6f47
    style BRZ fill:#cd7f32,stroke:#7a4a1e,color:#fff
    style SLV fill:#c0c0c0,stroke:#6b6b6b
```

Every PDF is detected by content, never by file name (a file can arrive under any name from
any source); every statement is validated against the balance it declares before a single row
reaches bronze; and a **backfill** command lets a parser fix reach every archived statement,
not just the next one — because a parsing bug doesn't always crash, it can just quietly get a
date or an amount wrong while the balances still add up.

## What's built (Phase 1 — Foundation)

| Layer | Status |
|---|---|
| PDF parsing & reconciliation (BCP) | ✅ Calibrated against real statements — see [below](#built-the-hard-way) |
| PDF parsing & reconciliation (Scotiabank) | ✅ Built — pending real-data validation (dual-currency credit card, opposite sign convention from BCP, handled explicitly) |
| Account kind (asset vs. liability) | ✅ Threaded through parsers → bronze → silver, so cross-bank analysis never assumes one sign convention |
| OCR fallback for scanned pages | ✅ |
| Multi-user, multi-account inbox → archive pipeline | ✅ |
| Bronze (Delta Lake on S3) | ✅ Write, idempotent re-ingest, backfill/replace |
| Silver (dbt) | ✅ Typed model + cross-statement continuity tests |
| CI: lint, types, tests, security, architecture contracts | ✅ Required on every PR |
| CI: impact-based performance benchmarking | ✅ Runs only when a change can affect it |
| CI: ephemeral per-PR environment (real S3, real `dbt build`) | ✅ Spins up, ingests, builds, tears down — nothing left behind |
| CI: base-vs-PR data diff | ✅ Every PR shows what the data itself would change, not just whether tests pass |
| Local exploration: DBeaver + Obsidian | ✅ The same DuckDB file dbt builds opens directly in DBeaver; `brain/` opens as an Obsidian vault, graph view included — see [SETUP.md](SETUP.md) |
| Orchestration, gold, ML, dashboard | Later phases — see [PROJECT.md](PROJECT.md) |

Every decision behind these is written down as an ADR, not just implemented and forgotten —
see [`brain/`](brain/README.md).

## Built the hard way

The BCP parser is the part of this project I'd point to first. It was built against a
synthetic fixture, then run against real statements — and it failed, repeatedly, in ways that
never showed up in a single test case:

1. The real layout didn't use the label text the parser expected at all.
2. A transaction's description started to the *left* of its own column header, corrupting the
   date next to it.
3. A cell printed a literal `0.00` beside the real amount in the next column.
4. Unrelated text leaked into an amount column and crashed the process outright.
5. A 4-page statement silently merged rows from different pages that happened to share a
   y-coordinate — the normal case for any multi-page statement, not an edge case.

Each one was found by running the tool for real, diagnosed from a **masked** layout dump (no
digit or name ever leaves the machine unmasked — see [ADR 0004](brain/decisions/0004-real-pdfs-never-leave-your-machine.md)),
fixed with a regression test reproducing the exact failure, and verified against the real
file before moving on. All four of the owner's real statements now parse and reconcile
end to end. The full story, fix by fix, is in [`brain/components/bcp-parser.md`](brain/components/bcp-parser.md).

## Engineering practices this repo actually follows

- **TDD throughout** — every commit history shows a failing test before its fix.
- **An architecture decision record for every real decision** — [`brain/decisions/`](brain/decisions),
  cross-linked with the components and concepts they justify.
- **Privacy by construction** — no full account number is ever stored (an HMAC identifies an
  account, never the number itself); no real PDF or `.env` is ever read by an AI agent working
  on this repo, only masked layout dumps the owner has reviewed.
- **A quality bar with teeth** — [`CONSTRAINTS.md`](CONSTRAINTS.md) defines the bar and a
  script (`floor_guard.py`) that fails a PR for quietly weakening it (a suppressed lint error,
  a deleted test, a relaxed config), not just for failing it outright.
- **Idempotent by design** — re-ingesting the same file twice adds zero rows; a `--dry-run`
  backfill shows exactly what a parser fix would change before it changes anything.

## Exploring the data

**The data:** `dbt build`'s own output, `dbt/pfp.duckdb`, is a real on-disk DuckDB database —
it opens directly in [DBeaver](https://dbeaver.io/) (or any DuckDB-aware SQL client), silver
with zero setup and bronze's raw Delta tables with a one-time DuckDB persistent-secret step.
Exact commands: **[SETUP.md §7](SETUP.md#7-browsing-the-lake-in-dbeaver)**.

**The architecture itself:** [`brain/`](brain/README.md) is plain Markdown with relative
links between notes, so it opens directly as an [Obsidian](https://obsidian.md/) vault —
every ADR, component and concept connected in a real graph, not just the Mermaid map on
GitHub. Steps: **[SETUP.md §8](SETUP.md#8-browsing-the-brain-in-obsidian)**.

## Getting started

Requirements, versions and the exact steps to run this locally: **[SETUP.md](SETUP.md)**.

The full project vision and phase roadmap (orchestration, gold, ML, a dashboard): **[PROJECT.md](PROJECT.md)**.

The architecture decision log — every *why*, not just the *what*: **[brain/](brain/README.md)**.
