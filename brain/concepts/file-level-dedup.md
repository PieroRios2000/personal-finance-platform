---
type: concept
phase: 1
---

# File-level deduplication

Recognize a PDF that was already ingested by its content, not by its name.

## How it applies here

- `file_sha256(path)` computes the content's SHA-256 with `hashlib.file_digest` (T7).
- `bronze/ingested_files` records every (user, hash) pair ingested, and `pfp ingest` skips a
  file that user already ingested (T14). The file name is never stored: it can contain account numbers.
- In the inbox (T12b), a repeated file is moved to `_duplicates/` instead of being filed again.
- The same PDF under a different name has the same hash, so it's skipped too.

## Limit

If the bank regenerates the PDF (say, with a different issue date), the bytes change and so
does the hash, even though the movements are the same. That case is covered by the second
layer: the [business key](business-key.md).

## Related

- [Idempotency](idempotency.md) — this is its first layer.
- [Business key](business-key.md) — the layer that covers regenerated PDFs.
- [Medallion architecture](medallion.md) — the file registry lives in bronze.
- [Phase 1](../phases/phase-1.md)
