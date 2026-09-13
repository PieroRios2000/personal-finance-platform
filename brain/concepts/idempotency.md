---
type: concept
phase: 1
---

# Idempotency

An operation is idempotent if running it twice leaves the same result as running it once.
Here it means **uploading the same statement twice never duplicates movements**.

## How it applies here

It's protected at two layers, because each one covers what the other misses:

| Layer | Detects | How | Where |
|---|---|---|---|
| File | The same PDF uploaded again | SHA-256 hash of the content | [File-level dedup](file-level-dedup.md) (T7, T14) |
| Transaction | The same movement in two different PDFs (January's statement and a "last 60 days" one) | [Business key](business-key.md) + MERGE in silver | Phase 2 |

T14's verification proves it directly: ingesting the same PDF twice adds 0 rows.

## Related

- [File-level dedup](file-level-dedup.md) — the first layer.
- [Business key](business-key.md) — the second layer.
- [Medallion architecture](medallion.md) — reprocessing a layer must also be idempotent.
- [Phase 1](../phases/phase-1.md)
