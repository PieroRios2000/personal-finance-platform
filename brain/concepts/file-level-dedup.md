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
does the hash, even though the movements are the same. The inbox organizer covers the common
case one step later: it compares what was *parsed* against the archived copy of the same
period, and identical content goes to `_duplicates/` instead of becoming a `_v2`
([ADR 0024](../decisions/0024-regenerated-pdfs-with-identical-content-are-duplicates.md)). A
regenerated file whose numbers really differ is still a new version, and the
[business key](business-key.md) is the layer that keeps its movements from duplicating.

## Related

- [Idempotency](idempotency.md) — this is its first layer.
- [Business key](business-key.md) — the layer that covers regenerated PDFs.
- [Medallion architecture](medallion.md) — the file registry lives in bronze.
- [Phase 1](../phases/phase-1.md)
